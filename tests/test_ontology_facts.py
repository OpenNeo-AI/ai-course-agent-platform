"""Ontology 事实回归:对已知事实与规则引擎计算结果做锁定断言(按知识域取数)。

前置:先在 server/ 下跑 scripts/build_kb.py 构建 data/app.db。
抽取错漏 → 修正抽取提示词重跑构建,或直接在库中修正实体/规则,本测试锁死结果。
运行:server/.venv/Scripts/python -m pytest ../tests/test_ontology_facts.py -v
"""
from __future__ import annotations

import pytest
from datetime import date

from app.core import db as dbmod
from app.core.ontology import engine

_DOM_CACHE: dict[str, int | None] = {}


def _dom(db, code: str) -> int | None:
    if code not in _DOM_CACHE:
        row = db.execute("SELECT id FROM domains WHERE code=?", (code,)).fetchone()
        _DOM_CACHE[code] = row["id"] if row else None
    return _DOM_CACHE[code]


def _a(db) -> int:
    return _dom(db, "domain-a")


def _b(db) -> int:
    return _dom(db, "domain-b")


def _built() -> bool:
    try:
        with dbmod.get_db() as db:
            a, b = _a(db), _b(db)
            return bool(a and b and engine.load_products(db, a)
                        and engine.load_products(db, b))
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _built(),
                                reason="data/app.db 尚未构建,先运行 server/scripts/build_kb.py")


# ---------- 知识域 domain-a:学生营 ----------

def _a_products(db):
    return {p["name"]: p for p in engine.load_products(db, _a(db))}


def test_a_three_class_types():
    with dbmod.get_db() as db:
        products = _a_products(db)
        assert len(products) >= 3
        bj = next(p for p in products.values() if p["attrs"].get("city") == "Beijing")
        sh = next(p for p in products.values() if p["attrs"].get("city") == "Shanghai")
        on = next(p for p in products.values() if p["attrs"].get("format") == "online")
        assert bj["attrs"]["fee_standard"] == 6980
        assert sh["attrs"]["fee_standard"] == 6980
        assert on["attrs"]["fee_standard"] == 3980
        assert bj["attrs"]["scale"] == 30 and bj["attrs"]["min_open"] == 15
        assert on["attrs"]["scale"] == 50 and on["attrs"]["min_open"] == 20


def test_a_three_periods():
    with dbmod.get_db() as db:
        periods = {p["name"]: p["attrs"] for p in engine.load_periods(db, _a(db))}
        assert len(periods) == 3
        p1 = next(a for n, a in periods.items() if "一" in n)
        assert p1["start"] == "2026-08-01" and p1["end"] == "2026-08-07"
        assert p1["enroll_deadline"] == "2026-07-25"
        assert p1["early_deadline"] == "2026-07-11"


def _a_fee(db, city, payment, period_name=None, **kw):
    products = _a_products(db)
    product = next(p for p in products.values() if p["attrs"].get("city") == city)
    period = None
    if period_name:
        period = engine.find_period(db, _a(db), name=period_name)
    else:
        period = engine.load_periods(db, _a(db))[0]
    return engine.calculate_fee(db, _a(db), product, payment_date=payment,
                                period=period, **kw)


def test_a_fee_early_bird():
    with dbmod.get_db() as db:
        r = _a_fee(db, "Beijing", date(2026, 7, 10))   # 开营前22日
        assert r["total"] == 5980 and r["applied_which"] == "early_bird"


def test_a_fee_no_discount():
    with dbmod.get_db() as db:
        r = _a_fee(db, "Beijing", date(2026, 7, 20))   # 开营前12日
        assert r["total"] == 6980 and r["applied_discount"] == 0


def test_a_fee_group_only():
    with dbmod.get_db() as db:
        r = _a_fee(db, "Beijing", date(2026, 7, 20), group_count=3)
        assert r["total"] == 6680 and r["applied_which"] == "group_discount"


def test_a_fee_stack_takes_higher():
    with dbmod.get_db() as db:
        r = _a_fee(db, "Beijing", date(2026, 7, 10), group_count=3)  # 早鸟1000 > 团报300
        assert r["total"] == 5980 and r["applied_which"] == "early_bird"


def test_a_fee_online_early():
    with dbmod.get_db() as db:
        r = _a_fee(db, "online", date(2026, 7, 10))
        assert r["total"] == 3280


def test_a_fee_boarding_optional():
    with dbmod.get_db() as db:
        r = _a_fee(db, "Beijing", date(2026, 7, 10), boarding=True)
        assert r["boarding_fee"] == 2360 and r["total"] == 5980 + 2360
        r2 = _a_fee(db, "online", date(2026, 7, 10), boarding=True)
        assert r2["boarding_fee"] == 0  # 线上无食宿


def test_a_refund_tiers():
    with dbmod.get_db() as db:
        a = _a(db)
        assert engine.refund_estimate(db, a, 5980, 16)["ratio"] == 0.9
        assert engine.refund_estimate(db, a, 5980, 10)["ratio"] == 0.5
        assert engine.refund_estimate(db, a, 5980, 10)["refund"] == 2990
        assert engine.refund_estimate(db, a, 5980, 3)["ratio"] == 0


# ---------- 知识域 domain-b:教师培训 ----------

def _b_products(db):
    return {p["name"]: p for p in engine.load_products(db, _b(db))}


def test_b_six_products_and_prices():
    with dbmod.get_db() as db:
        products = _b_products(db)
        assert len(products) >= 6
        by_level = {}
        for p in products.values():
            by_level.setdefault(p["attrs"].get("level"), set()).add(p["attrs"].get("fee"))
        assert by_level.get("L1") == {2980}
        assert by_level.get("L2") == {6980}
        assert by_level.get("L3") == {12800}


def _b_fee(db, name_kw, level, payment, **kw):
    product = next(p for p in engine.load_products(db, _b(db))
                   if name_kw in p["name"] and p["attrs"].get("level") == level)
    return engine.calculate_fee(db, _b(db), product, payment_date=payment, **kw)


def test_b_fee_early_subtract():
    with dbmod.get_db() as db:
        r = _b_fee(db, "集训", "L2", date(2026, 7, 15))   # 8/3 开课前19日 ≥14
        assert r["total"] == 5980 and r["applied_which"] == "early_bird"


def test_b_fee_late_no_discount():
    with dbmod.get_db() as db:
        r = _b_fee(db, "集训", "L2", date(2026, 7, 25))   # 开课前9日
        assert r["total"] == 6980


def test_b_fee_group_and_stack():
    with dbmod.get_db() as db:
        assert _b_fee(db, "集训", "L2", date(2026, 7, 25), group_count=3)["total"] == 6680
        r = _b_fee(db, "集训", "L2", date(2026, 7, 15), group_count=3)
        assert r["total"] == 5980 and r["applied_which"] == "early_bird"  # 1000 > 300
        assert _b_fee(db, "集训", "L1", date(2026, 7, 10))["total"] == 2480
        assert _b_fee(db, "集训", "L3", date(2026, 7, 25))["total"] == 10800  # 8/10 前16日≥14


def test_b_prerequisite():
    with dbmod.get_db() as db:
        b = _b(db)
        l2 = next(p for p in engine.load_products(db, b) if p["attrs"].get("level") == "L2")
        pre = engine.prerequisite_check(db, b, l2)
        assert pre and pre["level"] == "L2"
        l1 = next(p for p in engine.load_products(db, b) if p["attrs"].get("level") == "L1")
        assert engine.prerequisite_check(db, b, l1) is None


# ---------- 推荐筛选(策略为库内 recommend 规则,通用解释器执行) ----------

def test_recommend_a_beijing_offline():
    with dbmod.get_db() as db:
        r = engine.recommend(db, _a(db), {"city": "北京", "mode": "offline",
                                          "date_start": "2026-08-01", "date_end": "2026-08-07"})
        assert r["candidates"]
        top = r["candidates"][0]
        assert top["product"]["attrs"]["city"] == "Beijing"
        assert any("一" in p["name"] for p in top["periods"])


def test_recommend_a_date_conflict_all():
    with dbmod.get_db() as db:
        r = engine.recommend(db, _a(db), {"city": "北京", "mode": "offline",
                                          "date_start": "2026-09-01", "date_end": "2026-09-05"})
        assert not r["candidates"]
        assert r.get("note")


def test_recommend_a_insufficient_constraints():
    with dbmod.get_db() as db:
        r = engine.recommend(db, _a(db), {})
        assert r["need"] == ["城市/地点或线上偏好", "可用日期"]


def test_recommend_b_need():
    with dbmod.get_db() as db:
        r = engine.recommend(db, _b(db), {})
        assert r["need"] == ["可用日期", "是否能连续脱岗"]


def test_recommend_b_days_off_intensive():
    with dbmod.get_db() as db:
        r = engine.recommend(db, _b(db), {"level": "L2", "days_off_continuous": True,
                                          "date_start": "2026-08-03", "date_end": "2026-08-05"})
        assert r["candidates"]
        assert all("集训" in c["product"]["name"] for c in r["candidates"])


def test_recommend_b_weekend_when_no_days_off():
    with dbmod.get_db() as db:
        r = engine.recommend(db, _b(db), {"days_off_continuous": False,
                                          "date_start": "2026-08-08", "date_end": "2026-08-09"})
        assert r["candidates"]
        assert all("周末" in c["product"]["name"] for c in r["candidates"])
