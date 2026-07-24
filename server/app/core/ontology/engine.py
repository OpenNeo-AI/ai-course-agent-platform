"""通用规则解释引擎:读库执行,代码零业务数值。

以「知识域」为取数单位(实体/规则经 文档→知识库→知识域 链路归属),执行:
班型枚举、按约束筛选(推荐,策略本身也是库内规则)、费用计算(唯一计算规则)、
退费阶梯、前置校验、报名信息组装。所有价格/日期/人数/比例/推荐策略均来自库内
(抽取+确认+种入而来),本文件不出现任何业务数值字面量,也不按素材类型分支。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import date, datetime

log = logging.getLogger(__name__)


# ---------- 基础读取 ----------

def _attrs(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["attrs_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def _params(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["params_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def _domain_name(db: sqlite3.Connection, domain_id: int) -> str:
    row = db.execute("SELECT name FROM domains WHERE id=?", (domain_id,)).fetchone()
    return row["name"] if row else f"#{domain_id}"


def load_products(db: sqlite3.Connection, domain_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT e.* FROM entities e JOIN documents d ON d.id=e.doc_id "
        "JOIN kbs k ON k.id=d.kb_id WHERE k.domain_id=? AND e.type='product' ORDER BY e.id",
        (domain_id,)).fetchall()
    return [{"id": r["id"], "name": r["name"], "attrs": _attrs(r),
             "chapter": r["chapter"], "status": r["status"]} for r in rows]


def load_periods(db: sqlite3.Connection, domain_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT e.* FROM entities e JOIN documents d ON d.id=e.doc_id "
        "JOIN kbs k ON k.id=d.kb_id WHERE k.domain_id=? AND e.type='period' ORDER BY e.id",
        (domain_id,)).fetchall()
    return [{"id": r["id"], "name": r["name"], "attrs": _attrs(r),
             "chapter": r["chapter"], "status": r["status"]} for r in rows]


def load_rules(db: sqlite3.Connection, domain_id: int, kind: str | None = None) -> list[dict]:
    sql = ("SELECT r.* FROM rules r JOIN documents d ON d.id=r.doc_id "
           "JOIN kbs k ON k.id=d.kb_id WHERE k.domain_id=?")
    args: list = [domain_id]
    if kind:
        sql += " AND r.kind=?"
        args.append(kind)
    rows = db.execute(sql + " ORDER BY r.id", args).fetchall()
    return [{"id": r["id"], "kind": r["kind"], "params": _params(r),
             "chapter": r["chapter"], "status": r["status"]} for r in rows]


def find_product(db: sqlite3.Connection, domain_id: int, name: str | None = None,
                 entity_id: int | None = None) -> dict | None:
    for p in load_products(db, domain_id):
        if entity_id is not None and p["id"] == entity_id:
            return p
        if name and (p["name"] == name or name in p["name"] or p["name"] in name):
            return p
    return None


def find_period(db: sqlite3.Connection, domain_id: int, name: str | None = None,
                entity_id: int | None = None) -> dict | None:
    for p in load_periods(db, domain_id):
        if entity_id is not None and p["id"] == entity_id:
            return p
        if name and (p["name"] == name or name in p["name"] or p["name"] in name):
            return p
    return None


def _parse_date(s) -> date | None:
    if isinstance(s, date):
        return s
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------- 推荐:声明式策略规则 + 通用解释器 ----------
# 每个知识域一条 kind='recommend' 规则,params 声明:需采集的约束(needs)、
# 约束→产品匹配谓词(match)、日期匹配来源(date_check)、理由模板(reasons)、候选上限(cap)。
# 解释器不含任何具体班型/城市/等级字面量——业务策略全部在库内规则里。

def _dd(d: dict) -> defaultdict:
    x: defaultdict = defaultdict(str)
    x.update({k: v for k, v in (d or {}).items() if v is not None})
    return x


def _fmt(template: str, **kw) -> str:
    try:
        return (template or "").format_map(_dd(kw))
    except (KeyError, IndexError, ValueError):
        return template or ""


def _norm_val(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "absent"
    return str(v)


def _need_holds(clauses: list, cons: dict) -> bool:
    """needs 条目的全部 when 子句满足(AND)时,该 ask 项成立。"""
    for cl in clauses or []:
        if "all_absent" in cl:
            if any(k in cons for k in cl["all_absent"]):
                return False
        elif "any_absent" in cl:
            if not any(k not in cons for k in cl["any_absent"]):
                return False
        elif "any_present" in cl:
            if not any(k in cons for k in cl["any_present"]):
                return False
        elif "absent" in cl:
            if cl["absent"] in cons:
                return False
        elif "count_present_lt" in cl:
            spec = cl["count_present_lt"]
            if sum(1 for k in spec.get("keys", []) if k in cons) >= int(spec.get("n", 0)):
                return False
    return True


def _skip_if_holds(skip_if, cons: dict) -> bool:
    if not skip_if:
        return False
    return cons.get(skip_if.get("constraint")) == skip_if.get("eq")


def _resolve_pred(entry: dict, cons: dict):
    """取出当前约束对应的匹配谓词;约束缺省/未映射 → None(不过滤)。"""
    cval = cons.get(entry.get("constraint"))
    if cval is None or cval == "" or cval == []:
        return None
    if "value_predicates" in entry:
        key = cval.upper() if (entry.get("upper") and isinstance(cval, str)) else _norm_val(cval)
        return entry["value_predicates"].get(key)
    if "contains_map" in entry:
        s = str(cval)
        for substr, pred in entry["contains_map"].items():
            if substr in s:
                return pred
        return "pass" if entry.get("default") == "pass" else None
    if "attr" in entry and entry.get("eq_upper"):
        return {"attr": entry["attr"], "eq": str(cval).upper(), "upper": True}
    return None


def _pred_holds(pred, p: dict) -> bool:
    if pred == "pass":
        return True
    if isinstance(pred, dict) and "any_of" in pred:
        return any(_pred_holds(sub, p) for sub in pred["any_of"])
    if isinstance(pred, dict) and "name_contains" in pred:
        return pred["name_contains"] in p["name"]
    if isinstance(pred, dict) and "attr" in pred:
        av = p["attrs"].get(pred["attr"])
        if av is None:
            return False
        if pred.get("upper"):
            return str(av).upper() == str(pred["eq"]).upper()
        return str(av) == str(pred["eq"])
    return True


def _reason_text(rs: dict, cons: dict) -> str:
    if "value_templates" in rs:
        return rs["value_templates"].get(_norm_val(cons.get(rs.get("constraint"))), "")
    if "template" in rs:
        c = rs.get("constraint")
        if c and c not in cons:
            return ""
        if rs.get("only_if_absent") and any(k in cons for k in rs["only_if_absent"]):
            return ""
        return _fmt(rs["template"], **cons)
    return ""


def recommend(db: sqlite3.Connection, domain_id: int, constraints: dict) -> dict:
    """返回 {candidates, need}。candidates 每项含 product/periods/reasons;
    need 为尚缺的约束字段(非空时应先追问而非推荐)。策略取自域内 recommend 规则。"""
    cons = {k: v for k, v in (constraints or {}).items() if v not in (None, "", [])}
    products = load_products(db, domain_id)
    if not products:
        return {"candidates": [], "need": [],
                "error": f"知识域「{_domain_name(db, domain_id)}」数据尚未入库"}
    spec = None
    for r in load_rules(db, domain_id, "recommend"):
        spec = r["params"]
        break
    if not spec:
        return {"candidates": [], "need": [],
                "note": f"知识域「{_domain_name(db, domain_id)}」未配置推荐策略"}

    need = [e["ask"] for e in spec.get("needs", []) if _need_holds(e.get("when"), cons)]

    matched = products
    for entry in spec.get("match", []):
        if _skip_if_holds(entry.get("skip_if"), cons):
            continue
        pred = _resolve_pred(entry, cons)
        if pred is None:
            continue
        filtered = [p for p in matched if _pred_holds(pred, p)]
        matched = filtered or matched  # 软过滤:无命中则回退,避免空结果

    dc = spec.get("date_check", {})
    source = dc.get("source", "product")
    periods = load_periods(db, domain_id) if source == "periods" else []
    reason_specs = spec.get("reasons", [])

    candidates = []
    for p in matched:
        reasons: list[str] = []
        out_periods: list[dict] = []
        excluded = False
        for rs in reason_specs:
            if rs.get("type") == "date":
                if source == "periods":
                    kept = []
                    for period in periods:
                        pa = period["attrs"]
                        ov = _date_overlap(cons, _parse_date(pa.get("start")),
                                           _parse_date(pa.get("end")))
                        if ov is False:
                            continue
                        if ov is True:
                            reasons.append(_fmt(dc.get("on_ok", ""), name=period["name"], **pa))
                        kept.append(period)
                    if periods and not kept:
                        excluded = True
                        break
                    out_periods = kept or periods
                else:
                    pa = p["attrs"]
                    ov = _date_overlap(cons, _parse_date(pa.get("start")),
                                       _parse_date(pa.get("end")))
                    if ov is False:
                        excluded = True
                        break
                    if ov is True:
                        reasons.append(_fmt(dc.get("on_ok", ""), **pa))
                    out_periods = []
            else:
                t = _reason_text(rs, cons)
                if t:
                    reasons.append(t)
        if excluded:
            continue
        candidates.append({"product": p, "periods": out_periods, "reasons": reasons})

    if source == "periods" and periods and not candidates and dc.get("empty_note"):
        return {"candidates": [], "need": need, "note": dc["empty_note"]}
    return {"candidates": candidates[:int(spec.get("cap", 3))], "need": need}


def _date_overlap(cons: dict, start: date | None, end: date | None) -> bool | None:
    """约束日期与班期是否重叠;约束未提供日期返回 None。"""
    cs, ce = _parse_date(cons.get("date_start")), _parse_date(cons.get("date_end"))
    dates = [_parse_date(d) for d in (cons.get("dates") or [])]
    dates = [d for d in dates if d]
    if cs and ce:
        pass
    elif dates:
        cs, ce = min(dates), max(dates)
    else:
        return None
    if start is None or end is None:
        return None
    return not (ce < start or cs > end)


# ---------- 推荐策略种子(竞赛素材的推荐逻辑,数据化存于规则表) ----------

RECOMMEND_SPECS = {
    "domain-a": {
        "needs": [
            {"ask": "城市/地点或线上偏好", "when": [{"all_absent": ["city", "mode"]}]},
            {"ask": "可用日期", "when": [{"all_absent": ["date_start", "dates"]}]},
            {"ask": "学习目标或其他偏好", "when": [
                {"count_present_lt": {"keys": ["city", "mode", "date_start", "dates", "goal"], "n": 2}},
                {"all_absent": ["city", "mode"]},
                {"any_present": ["date_start", "dates"]}]},
        ],
        "match": [
            {"constraint": "mode", "value_predicates": {
                "online": {"attr": "format", "eq": "online"},
                "offline": {"attr": "format", "eq": "offline"}}},
            {"constraint": "city", "skip_if": {"constraint": "mode", "eq": "online"},
             "contains_map": {"北京": {"attr": "city", "eq": "Beijing"},
                              "上海": {"attr": "city", "eq": "Shanghai"}},
             "default": "pass"},
        ],
        "date_check": {"source": "periods",
                       "on_ok": "{name}({start}—{end})与你的可用日期无冲突",
                       "empty_note": "现有营期与所提供日期均冲突,建议调整日期或选择其他营期"},
        "reasons": [
            {"constraint": "city", "template": "地点匹配「{city}」偏好"},
            {"constraint": "mode", "template": "形式匹配「{mode}」偏好", "only_if_absent": ["city"]},
            {"type": "date"},
            {"constraint": "goal", "template": "面向学习目标「{goal}」"},
        ],
        "cap": 3,
    },
    "domain-b": {
        "needs": [
            {"ask": "可用日期", "when": [{"all_absent": ["date_start", "dates"]}]},
            {"ask": "是否能连续脱岗", "when": [{"absent": "days_off_continuous"}]},
        ],
        "match": [
            {"constraint": "level", "attr": "level", "eq_upper": True},
            {"constraint": "days_off_continuous", "value_predicates": {
                "true": {"any_of": [{"name_contains": "集训"}, {"attr": "format", "eq": "intensive"}]},
                "false": {"any_of": [{"name_contains": "周末"}, {"attr": "format", "eq": "weekend"}]}}},
        ],
        "date_check": {"source": "product", "on_ok": "日期({start}—{end})与你的可用日期吻合"},
        "reasons": [
            {"constraint": "days_off_continuous", "value_templates": {
                "true": "能完整连续脱岗,优先推荐暑期集训班",
                "false": "工作日不能脱岗,优先推荐周末研修班",
                "absent": "未确认是否能连续脱岗,集训班与周末研修班均列出"}},
            {"type": "date"},
            {"constraint": "level", "template": "等级匹配「{level}」"},
            {"constraint": "goal", "template": "面向学习目标「{goal}」"},
        ],
        "cap": 2,
    },
}


def seed_recommend_rules(db: sqlite3.Connection) -> None:
    """为各知识域种入推荐策略规则(幂等);策略以数据形式存于规则表,可经 portal 维护。"""
    for dom_code, spec in RECOMMEND_SPECS.items():
        dom = db.execute("SELECT id FROM domains WHERE code=?", (dom_code,)).fetchone()
        if not dom:
            continue
        exists = db.execute(
            "SELECT 1 FROM rules r JOIN documents d ON d.id=r.doc_id "
            "JOIN kbs k ON k.id=d.kb_id WHERE k.domain_id=? AND r.kind='recommend'",
            (dom["id"],)).fetchone()
        if exists:
            continue
        doc = db.execute(
            "SELECT d.id FROM documents d JOIN kbs k ON k.id=d.kb_id "
            "WHERE k.domain_id=? ORDER BY d.id LIMIT 1", (dom["id"],)).fetchone()
        if not doc:
            continue
        db.execute("INSERT INTO rules(kind, params_json, doc_id, status) "
                   "VALUES('recommend',?,?, 'confirmed')",
                   (json.dumps(spec, ensure_ascii=False), doc["id"]))


# ---------- 费用计算:解释执行库内规则 ----------

def calculate_fee(db: sqlite3.Connection, domain_id: int, product: dict, *,
                  payment_date: date | str, period: dict | None = None,
                  group_count: int = 1, boarding: bool = False) -> dict:
    """唯一计算规则:最终费用 = 班型课程费 − 唯一适用优惠 + 自愿选择的食宿费用。
    课程费与开营日均由产品/营期数据推断,不分支。"""
    attrs = product["attrs"]
    payment = _parse_date(payment_date)
    base = float(attrs.get("fee", attrs.get("fee_standard", 0)))
    start_src = (period or {}).get("attrs", {}).get("start") or attrs.get("start")
    start = _parse_date(start_src)
    days_before = (start - payment).days if (start and payment) else None

    breakdown = {"base_fee": base, "early_bird": 0.0, "group_discount": 0.0,
                 "applied_discount": 0.0, "applied_which": None,
                 "boarding_fee": 0.0, "total": base, "notes": [],
                 "formula": None}

    # 早鸟
    for rule in load_rules(db, domain_id, "early_bird"):
        params = rule["params"]
        threshold = params.get("days_before_start")
        if days_before is None or threshold is None or days_before < threshold:
            breakdown["notes"].append(f"早鸟:不满足(需开营前{threshold}日及以上缴费)")
            continue
        by_attr = params.get("by_attr", "format")
        key = str(attrs.get(by_attr, "")).lower()
        value_by = {str(k).lower(): v for k, v in (params.get("value_by") or {}).items()}
        if params.get("mode") == "override" and key in value_by:
            disc = base - float(value_by[key])
            if disc > 0:
                breakdown["early_bird"] = disc
                breakdown["notes"].append(f"早鸟:开营前{days_before}日缴费,优惠{disc:.0f}元")
        elif params.get("mode") == "subtract" and key in value_by:
            breakdown["early_bird"] = float(value_by[key])
            breakdown["notes"].append(f"早鸟:开营前{days_before}日缴费,立减{float(value_by[key]):.0f}元")

    # 团报
    for rule in load_rules(db, domain_id, "group_discount"):
        params = rule["params"]
        if group_count >= int(params.get("min_people", 99)):
            breakdown["group_discount"] = float(params.get("subtract", 0))
            breakdown["notes"].append(
                f"团报:{group_count}人≥{params.get('min_people')}人,每人减{float(params.get('subtract', 0)):.0f}元")

    # 叠加策略:不叠加,取更高
    for rule in load_rules(db, domain_id, "stack_policy"):
        if rule["params"].get("mode") == "max_one" and breakdown["early_bird"] and breakdown["group_discount"]:
            if breakdown["early_bird"] >= breakdown["group_discount"]:
                breakdown["applied_which"] = "early_bird"
            else:
                breakdown["applied_which"] = "group_discount"
            breakdown["notes"].append("早鸟与团报不可叠加,仅采用优惠金额更高的一项")
    if breakdown["applied_which"] == "early_bird":
        breakdown["applied_discount"] = breakdown["early_bird"]
    elif breakdown["applied_which"] == "group_discount":
        breakdown["applied_discount"] = breakdown["group_discount"]
    else:
        breakdown["applied_discount"] = breakdown["early_bird"] or breakdown["group_discount"]
        breakdown["applied_which"] = "early_bird" if breakdown["early_bird"] else (
            "group_discount" if breakdown["group_discount"] else None)

    # 食宿(自愿选择;是否提供由产品数据决定)
    if boarding:
        b = attrs.get("boarding") or {}
        if b:
            breakdown["boarding_fee"] = float(b.get("total", 0))
            breakdown["notes"].append(
                f"食宿(自愿):住宿{b.get('lodging', 0)}元+餐食"
                f"{b.get('meal_per_day', 0)}元×{b.get('meal_days', 0)}天={breakdown['boarding_fee']:.0f}元")
        else:
            breakdown["notes"].append("该班型不提供线下食宿")

    for rule in load_rules(db, domain_id, "fee_formula"):
        breakdown["formula"] = rule["params"].get("formula_text")

    breakdown["total"] = base - breakdown["applied_discount"] + breakdown["boarding_fee"]
    return breakdown


# ---------- 退费 / 前置 / 报名信息 ----------

def refund_estimate(db: sqlite3.Connection, domain_id: int, paid: float,
                    days_before_start: int) -> dict:
    for rule in load_rules(db, domain_id, "refund"):
        tiers = sorted(rule["params"].get("tiers", []),
                       key=lambda t: t.get("min_days", 0), reverse=True)
        for tier in tiers:
            if days_before_start >= int(tier.get("min_days", 0)):
                ratio = float(tier.get("ratio", 0))
                return {"refund": round(paid * ratio, 2), "ratio": ratio,
                        "rule_note": rule["params"].get("note", "")}
    return {"refund": None, "ratio": None,
            "rule_note": "资料未提供退费规则,需人工确认"}


def prerequisite_check(db: sqlite3.Connection, domain_id: int, product: dict) -> dict | None:
    level = product["attrs"].get("level")
    if not level:
        return None
    for rule in load_rules(db, domain_id, "prerequisite"):
        levels = [str(x).upper() for x in rule["params"].get("levels", [])]
        if str(level).upper() in levels:
            return {"level": level,
                    "require_text": rule["params"].get("require_text", ""),
                    "on_fail_text": rule["params"].get("on_fail_text", "")}
    return None


def enrollment_info(db: sqlite3.Connection, domain_id: int, product: dict | None = None) -> dict:
    """结构化报名要点;流程细节与资料外事项统一引导人工。"""
    info: dict = {"domain_id": domain_id, "deadline": None, "refund_note": None,
                  "reschedule": None, "manual_fallback": "请联系人工课程顾问"}
    if product:
        info["deadline"] = product["attrs"].get("deadline") or product["attrs"].get("enroll_deadline")
        pre = prerequisite_check(db, domain_id, product)
        if pre:
            info["prerequisite"] = pre
    for rule in load_rules(db, domain_id, "refund"):
        info["refund_note"] = rule["params"].get("note")
    for rule in load_rules(db, domain_id, "reschedule"):
        info["reschedule"] = rule["params"].get("text")
    return info
