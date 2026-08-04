"""支付渠道:CHANNELS 注册表。
- MockChannel:演示环境模拟支付(测试单允许),确认即成功。
- WechatNativeChannel:微信 Native 扫码支付(V2 API,MD5 签名,XML)。
  参照 OpenNeo server/utils/wechatPay.js 移植,并补齐其缺失的服务端回调验签。
- AlipayPageChannel:支付宝电脑网站支付(alipay.trade.page.pay,RSA2 签名)。
  参照 OpenNeo server/utils/alipay.js 移植。

真实渠道需 .env 配置(与 OpenNeo 变量名一致):
  WECHAT_APP_ID / WECHAT_MCH_ID / WECHAT_API_KEY / WECHAT_NOTIFY_URL
  ALIPAY_APP_ID / ALIPAY_MERCHANT_PRIVATE_KEY / ALIPAY_ALIPAY_PUBLIC_KEY / ALIPAY_NOTIFY_URL
未配置的渠道自动降级不可用,下单走 mock。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import sqlite3
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

from . import config
from .db import get_db, log_action

log = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def gen_out_trade_no() -> str:
    """商户订单号:时间戳 + 随机(≤32位)。"""
    return datetime.now(_CST).strftime("%Y%m%d%H%M%S") + secrets.token_hex(4)


class PaymentChannel:
    code = ""
    name = ""

    def configured(self) -> bool:
        return False

    def create(self, order: dict) -> dict:
        """下单;返回展示信息(mock 提示 / code_url / pay_url)。"""
        return {}

    def query(self, order: dict) -> str:
        """主动向渠道查单:'paid' / 'pending' / 'failed'。"""
        return "pending"

    def confirm(self, order: dict) -> bool:
        """同步确认(仅 mock 渠道使用);真实渠道走 query/回调。"""
        return False

    def parse_callback(self, body: bytes, content_type: str) -> dict:
        """回调解析+验签;返回 {out_trade_no, trade_no};失败抛 ValueError。"""
        raise ValueError("该渠道不支持回调")


class MockChannel(PaymentChannel):
    """模拟支付:确认即成功(演示环境,明确标注不产生真实扣款)。"""
    code = "mock"
    name = "模拟支付"

    def configured(self) -> bool:
        return True

    def create(self, order: dict) -> dict:
        return {"notice": "演示环境:点击确认即模拟支付成功,不产生真实扣款。"}

    def query(self, order: dict) -> str:
        return "pending"

    def confirm(self, order: dict) -> bool:
        return True


# ---------- 微信支付(Native 扫码,V2 MD5) ----------

class WechatNativeChannel(PaymentChannel):
    code = "wechat"
    name = "微信支付"

    def configured(self) -> bool:
        return bool(config.env("WECHAT_APP_ID") and config.env("WECHAT_MCH_ID")
                    and config.env("WECHAT_API_KEY"))

    def _sign(self, params: dict) -> str:
        qs = "&".join(f"{k}={params[k]}" for k in sorted(params)
                      if params[k] not in (None, "") and k != "sign")
        return hashlib.md5((qs + "&key=" + (config.env("WECHAT_API_KEY") or "")
                            ).encode("utf-8")).hexdigest().upper()

    def _xml(self, params: dict) -> bytes:
        inner = "".join(f"<{k}>{params[k]}</{k}>" for k in params)
        return f"<xml>{inner}</xml>".encode("utf-8")

    def _parse_xml(self, body: bytes) -> dict:
        root = ET.fromstring(body)
        return {c.tag: c.text for c in root}

    def create(self, order: dict) -> dict:
        params = {
            "appid": config.env("WECHAT_APP_ID"),
            "mch_id": config.env("WECHAT_MCH_ID"),
            "nonce_str": secrets.token_hex(16),
            "body": f"AI教育顾问SaaS-{order['plan_name']}",
            "out_trade_no": order["out_trade_no"],
            "total_fee": int(round(float(order["amount"]) * 100)),  # 单位:分
            "spbill_create_ip": "127.0.0.1",
            "notify_url": config.env("WECHAT_NOTIFY_URL") or "",
            "trade_type": "NATIVE",
        }
        params["sign"] = self._sign(params)
        resp = httpx.post("https://api.mch.weixin.qq.com/pay/unifiedorder",
                          data=self._xml(params), timeout=20)
        data = self._parse_xml(resp.content)
        if data.get("return_code") != "SUCCESS" or data.get("result_code") != "SUCCESS":
            raise ValueError(data.get("return_msg") or data.get("err_code_des")
                             or "微信下单失败")
        return {"code_url": data.get("code_url", "")}

    def query(self, order: dict) -> str:
        params = {
            "appid": config.env("WECHAT_APP_ID"),
            "mch_id": config.env("WECHAT_MCH_ID"),
            "out_trade_no": order["out_trade_no"],
            "nonce_str": secrets.token_hex(16),
        }
        params["sign"] = self._sign(params)
        try:
            resp = httpx.post("https://api.mch.weixin.qq.com/pay/orderquery",
                              data=self._xml(params), timeout=20)
            data = self._parse_xml(resp.content)
        except Exception as e:  # noqa: BLE001
            log.warning("微信查单异常: %s", e)
            return "pending"
        state = data.get("trade_state")
        if state == "SUCCESS":
            order["trade_no"] = data.get("transaction_id", "")
            return "paid"
        if state in ("CLOSED", "REVOKED", "PAYERROR"):
            return "failed"
        return "pending"

    def parse_callback(self, body: bytes, content_type: str) -> dict:
        data = self._parse_xml(body)
        sign = data.pop("sign", "")
        if self._sign(data) != sign:
            raise ValueError("微信回调验签失败")
        if data.get("return_code") != "SUCCESS" or data.get("result_code") != "SUCCESS":
            raise ValueError("微信回调状态非成功")
        return {"out_trade_no": data.get("out_trade_no", ""),
                "trade_no": data.get("transaction_id", "")}


# ---------- 支付宝(电脑网站支付,RSA2) ----------

def _norm_pem(pem: str) -> str:
    """env 中的 PEM 常以字面 \\n 转义存储,先还原为真实换行。"""
    return pem.strip().replace("\\n", "\n")


def _load_private_key(pem: str):
    from cryptography.hazmat.primitives import serialization
    pem = _norm_pem(pem)
    if "BEGIN" not in pem:
        pem = ("-----BEGIN PRIVATE KEY-----\n"
               + "\n".join(pem[i:i + 64] for i in range(0, len(pem), 64))
               + "\n-----END PRIVATE KEY-----")
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def _load_public_key(pem: str):
    from cryptography.hazmat.primitives import serialization
    pem = _norm_pem(pem)
    if "BEGIN" not in pem:
        pem = ("-----BEGIN PUBLIC KEY-----\n"
               + "\n".join(pem[i:i + 64] for i in range(0, len(pem), 64))
               + "\n-----END PUBLIC KEY-----")
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def _rsa_sign(content: str, private_pem: str) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    key = _load_private_key(private_pem)
    sig = key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode("utf-8")


def _rsa_verify(content: str, sign_b64: str, public_pem: str) -> bool:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        _load_public_key(public_pem).verify(
            base64.b64decode(sign_b64), content.encode("utf-8"),
            padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:  # noqa: BLE001
        return False


class AlipayPageChannel(PaymentChannel):
    code = "alipay"
    name = "支付宝"
    GATEWAY = "https://openapi.alipay.com/gateway.do"

    def configured(self) -> bool:
        return bool(config.env("ALIPAY_APP_ID")
                    and config.env("ALIPAY_MERCHANT_PRIVATE_KEY")
                    and config.env("ALIPAY_ALIPAY_PUBLIC_KEY"))

    def _signed_params(self, method: str, biz_content: dict) -> dict:
        params = {
            "app_id": config.env("ALIPAY_APP_ID"),
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": config.env("ALIPAY_NOTIFY_URL") or "",
            "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        }
        content = "&".join(f"{k}={params[k]}" for k in sorted(params))
        params["sign"] = _rsa_sign(content, config.env("ALIPAY_MERCHANT_PRIVATE_KEY") or "")
        return params

    def create(self, order: dict) -> dict:
        params = self._signed_params("alipay.trade.page.pay", {
            "out_trade_no": order["out_trade_no"],
            "total_amount": f"{float(order['amount']):.2f}",
            "subject": f"AI教育顾问SaaS-{order['plan_name']}",
            "product_code": "FAST_INSTANT_TRADE_PAY",
        })
        pay_url = self.GATEWAY + "?" + urllib.parse.urlencode(params)
        return {"pay_url": pay_url}

    def query(self, order: dict) -> str:
        params = self._signed_params("alipay.trade.query",
                                     {"out_trade_no": order["out_trade_no"]})
        try:
            resp = httpx.post(self.GATEWAY, data=params, timeout=20)
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.warning("支付宝查单异常: %s", e)
            return "pending"
        body = data.get("alipay_trade_query_response", {})
        order["trade_no"] = body.get("trade_no", "")
        status = body.get("trade_status")
        if status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            return "paid"
        if status == "TRADE_CLOSED":
            return "failed"
        return "pending"

    def parse_callback(self, body: bytes, content_type: str) -> dict:
        form = urllib.parse.parse_qs(body.decode("utf-8"))
        params = {k: v[0] for k, v in form.items()}
        sign = params.pop("sign", "")
        params.pop("sign_type", None)
        content = "&".join(f"{k}={params[k]}" for k in sorted(params))
        if not _rsa_verify(content, sign, config.env("ALIPAY_ALIPAY_PUBLIC_KEY") or ""):
            raise ValueError("支付宝回调验签失败")
        if params.get("trade_status") not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            raise ValueError("支付宝回调状态非成功")
        return {"out_trade_no": params.get("out_trade_no", ""),
                "trade_no": params.get("trade_no", "")}


CHANNELS: dict[str, PaymentChannel] = {
    MockChannel.code: MockChannel(),
    WechatNativeChannel.code: WechatNativeChannel(),
    AlipayPageChannel.code: AlipayPageChannel(),
}


def channel_of(code: str) -> PaymentChannel:
    ch = CHANNELS.get(code or "mock")
    if not ch or not ch.configured():
        return CHANNELS["mock"]
    return ch


def channels_status() -> list[dict]:
    """渠道可用性(前端展示:未配置的渠道置灰)。"""
    return [{"code": c.code, "name": c.name, "configured": c.configured()}
            for c in CHANNELS.values()]


def create_order(tenant_id: int, plan_code: str, channel_code: str = "mock") -> dict:
    with get_db() as db:
        plan = db.execute("SELECT * FROM plans WHERE code=?", (plan_code,)).fetchone()
        if not plan:
            raise ValueError("套餐不存在")
        # 严格校验:指定渠道不在启用列表或未配置 → 报错,不做静默回退
        ch = CHANNELS.get(channel_code or "mock")
        if not ch or not ch.configured():
            raise ValueError("该支付渠道不可用")
        out_trade_no = gen_out_trade_no()
        cur = db.execute(
            "INSERT INTO payment_orders(tenant_id, plan_code, channel, amount, out_trade_no) "
            "VALUES(?,?,?,?,?)",
            (tenant_id, plan_code, ch.code, plan["price_monthly"], out_trade_no))
        order = dict(db.execute("SELECT * FROM payment_orders WHERE id=?",
                                (cur.lastrowid,)).fetchone())
    order["plan_name"] = plan["name"]
    try:
        pay_info = ch.create(order)
    except Exception as e:  # noqa: BLE001
        log.exception("渠道下单失败")
        raise ValueError(f"下单失败:{e}")
    return {**order, "channel_name": ch.name, "pay_info": pay_info}


def pay_success(order_id: int, verified: bool = False, trade_no: str = "") -> dict:
    """支付成功:订单置 paid 并升级订阅(幂等)。
    verified=True 表示已由回调/查单确认(mock 渠道走 confirm)。"""
    with get_db() as db:
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise ValueError("订单不存在")
        if order["status"] == "paid":
            return _result(db, order)
        ch = CHANNELS.get(order["channel"], CHANNELS["mock"])
        if not verified:
            if not isinstance(ch, MockChannel) or not ch.configured():
                raise ValueError("该订单需经渠道回调/查询确认")
            if not ch.confirm(dict(order)):  # type: ignore[attr-defined]
                db.execute("UPDATE payment_orders SET status='failed' WHERE id=?", (order_id,))
                raise ValueError("支付未成功")
        db.execute("UPDATE payment_orders SET status='paid', paid_at=?, trade_no=? WHERE id=?",
                   (_now(), trade_no or order["trade_no"] or "", order_id))
        db.execute(
            "INSERT INTO subscriptions(tenant_id, plan_code, status, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(tenant_id) DO UPDATE SET plan_code=excluded.plan_code, "
            "status='active', updated_at=excluded.updated_at",
            (order["tenant_id"], order["plan_code"], "active", _now()))
        log_action(db, "subscription_upgrade", f"tenant:{order['tenant_id']}",
                   f"plan={order['plan_code']} channel={order['channel']} order={order_id}")
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
        return _result(db, order)


def pay_by_out_trade_no(out_trade_no: str, trade_no: str = "") -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT id FROM payment_orders WHERE out_trade_no=?",
                         (out_trade_no,)).fetchone()
    if not row:
        return None
    return pay_success(row["id"], verified=True, trade_no=trade_no)


def query_order(order_id: int) -> dict:
    """前端轮询:主动向渠道查单,成功则落库升级。"""
    with get_db() as db:
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise ValueError("订单不存在")
    if order["status"] == "paid":
        with get_db() as db:
            return _result(db, order)
    ch = CHANNELS.get(order["channel"], CHANNELS["mock"])
    state = ch.query(dict(order))
    if state == "paid":
        return pay_success(order_id, verified=True, trade_no=order.get("trade_no", ""))
    return {"order_id": order_id, "status": "failed" if state == "failed" else "pending"}


def _result(db: sqlite3.Connection, order: sqlite3.Row) -> dict:
    from . import tenancy
    return {"order_id": order["id"], "status": order["status"],
            "plan_code": order["plan_code"],
            "subscription": tenancy.subscription_of(db, order["tenant_id"]),
            "quota": tenancy.quota_state(db, order["tenant_id"])}
