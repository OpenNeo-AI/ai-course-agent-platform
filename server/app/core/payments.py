"""支付渠道:注册表 + 内置模拟支付(演示环境,测试单允许)。

真实渠道挂接方式:实现 PaymentChannel 子类(对接支付宝/微信沙箱),
注册进 CHANNELS 并在 .env 配置密钥即可,订单/升级流程代码零改动。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .db import get_db, log_action

_CST = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


class PaymentChannel:
    """支付渠道接口。create 返回展示信息;confirm 返回是否支付成功。"""
    code = ""
    name = ""
    sandbox = False

    def create(self, order: dict) -> dict:
        return {}

    def confirm(self, order: dict) -> bool:
        raise NotImplementedError


class MockChannel(PaymentChannel):
    """模拟支付:确认即成功,用于演示支付闭环(明确标注演示环境,不产生真实收款)。"""
    code = "mock"
    name = "模拟支付(演示环境)"
    sandbox = True

    def create(self, order: dict) -> dict:
        return {"notice": "演示环境:点击确认即模拟支付成功,不产生真实扣款。"}

    def confirm(self, order: dict) -> bool:
        return True


# 渠道注册表:支付宝/微信沙箱由使用方实现后在此注册
CHANNELS: dict[str, PaymentChannel] = {
    MockChannel.code: MockChannel(),
}


def channel_of(code: str) -> PaymentChannel | None:
    return CHANNELS.get(code or "mock")


def create_order(tenant_id: int, plan_code: str, channel_code: str = "mock") -> dict:
    with get_db() as db:
        plan = db.execute("SELECT * FROM plans WHERE code=?", (plan_code,)).fetchone()
        if not plan:
            raise ValueError("套餐不存在")
        ch = channel_of(channel_code)
        if not ch:
            raise ValueError("支付渠道不可用")
        cur = db.execute(
            "INSERT INTO payment_orders(tenant_id, plan_code, channel, amount) VALUES(?,?,?,?)",
            (tenant_id, plan_code, ch.code, plan["price_monthly"]))
        order = dict(db.execute("SELECT * FROM payment_orders WHERE id=?",
                                (cur.lastrowid,)).fetchone())
    return {**order, "channel_name": ch.name, "channel_info": ch.create(order)}


def pay_success(order_id: int) -> dict:
    """渠道回调/确认成功:订单置 paid 并升级订阅(幂等)。"""
    with get_db() as db:
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise ValueError("订单不存在")
        if order["status"] == "paid":
            return _result(db, order)
        ch = channel_of(order["channel"])
        if not ch or not ch.confirm(dict(order)):
            db.execute("UPDATE payment_orders SET status='failed' WHERE id=?", (order_id,))
            raise ValueError("支付未成功")
        db.execute("UPDATE payment_orders SET status='paid', paid_at=? WHERE id=?",
                   (_now(), order_id))
        db.execute(
            "INSERT INTO subscriptions(tenant_id, plan_code, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(tenant_id) DO UPDATE SET plan_code=excluded.plan_code, "
            "status='active', updated_at=excluded.updated_at",
            (order["tenant_id"], order["plan_code"], _now()))
        log_action(db, "subscription_upgrade", f"tenant:{order['tenant_id']}",
                   f"plan={order['plan_code']} channel={order['channel']} order={order_id}")
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
        return _result(db, order)


def _result(db: sqlite3.Connection, order: sqlite3.Row) -> dict:
    from . import tenancy
    return {"order_id": order["id"], "status": order["status"],
            "plan_code": order["plan_code"],
            "subscription": tenancy.subscription_of(db, order["tenant_id"]),
            "quota": tenancy.quota_state(db, order["tenant_id"])}
