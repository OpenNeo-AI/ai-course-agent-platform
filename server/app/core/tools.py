"""核心工具:一份实现,三种暴露(Agent 循环 / MCP server / REST)。

所有工具返回可 JSON 序列化 dict,内部兜底异常,不向外抛。取数与计算均以「知识域」
为范围(由调用方注入 domain_ids / kb_ids):精确事实(价格/日期)来自 ontology 引擎,
描述性内容来自多路检索 + LLM 生成。无素材概念,无范围外数据可见。
"""
from __future__ import annotations

import logging

from . import config, llm
from .db import get_db
from .ontology import engine
from .retrieval import search

log = logging.getLogger(__name__)

HUMAN_FALLBACK = "请联系人工课程顾问"


def _domain_name(db, domain_id: int) -> str:
    row = db.execute("SELECT name FROM domains WHERE id=?", (domain_id,)).fetchone()
    return row["name"] if row else f"知识域#{domain_id}"


def _domain_doc_titles(db, domain_id: int) -> list[str]:
    rows = db.execute(
        "SELECT DISTINCT d.title FROM documents d JOIN kbs k ON k.id=d.kb_id "
        "WHERE k.domain_id=? AND d.title IS NOT NULL AND d.title<>'' ORDER BY d.id",
        (domain_id,)).fetchall()
    return [r["title"] for r in rows]


def _domain_source_label(db, domain_id: int) -> str:
    titles = _domain_doc_titles(db, domain_id)
    return ("《" + "》、《".join(titles) + "》") if titles else _domain_name(db, domain_id)


def _rule_chapters(db, domain_id: int) -> list[str]:
    chapters = []
    for r in engine.load_rules(db, domain_id):
        ch = r.get("chapter")
        if ch and ch not in chapters:
            chapters.append(ch)
    return chapters


def _source_note(db, domain_id: int) -> str:
    """费用/清单类回答的引用标注:来自库内规则的章节溯源 + 文档来源。"""
    chapters = _rule_chapters(db, domain_id)
    base = _domain_source_label(db, domain_id)
    return "— 出自 " + base + ("·" + "、".join(chapters[:2]) if chapters else "")


def _source_cite(db, domain_id: int) -> list[dict]:
    """结构化引用条目(与 _source_note 同源),供前端以卡片渲染;含关键原文语句。"""
    src = _domain_source_label(db, domain_id)
    rows = db.execute(
        "SELECT r.chapter, r.raw_excerpt FROM rules r "
        "JOIN documents d ON d.id=r.doc_id JOIN kbs k ON k.id=d.kb_id "
        "WHERE k.domain_id=? AND r.kind<>'recommend' "
        "AND r.chapter IS NOT NULL AND r.chapter<>'' ORDER BY r.id",
        (domain_id,)).fetchall()
    items, seen = [], set()
    for r in rows:
        ch = r["chapter"]
        if ch in seen:
            continue
        seen.add(ch)
        items.append({"source": src, "chapter": ch,
                      "excerpt": search.key_excerpt(r["raw_excerpt"] or "")})
        if len(items) >= 2:
            break
    return items or [{"source": src, "chapter": "", "excerpt": ""}]


def _discount_summary(db, domain_id: int) -> list[dict]:
    """知识域级优惠规则概览(数值来自库内规则记录,供模型原样引用)。"""
    summary = []
    for r in engine.load_rules(db, domain_id):
        p = r["params"]
        if r["kind"] == "early_bird":
            summary.append({"kind": "early_bird", "mode": p.get("mode"),
                            "days_before_start": p.get("days_before_start"),
                            "value_by": p.get("value_by")})
        elif r["kind"] == "group_discount":
            summary.append({"kind": "group_discount",
                            "min_people": p.get("min_people"),
                            "subtract": p.get("subtract"),
                            "scope_note": p.get("scope_note")})
        elif r["kind"] == "stack_policy":
            summary.append({"kind": "stack_policy", "mode": p.get("mode"),
                            "note": p.get("note")})
    return summary


def product_brief(db, domain_id: int, product: dict) -> dict:
    """班型/产品的结构化简介(供推荐与列表展示);字段按数据存在性输出。"""
    a = product["attrs"]
    brief = {"id": product["id"], "name": product["name"],
             "format": a.get("format"), "venue": a.get("venue")}
    if a.get("fee_standard") is not None:
        brief.update(fee_standard=a.get("fee_standard"), scale=a.get("scale"),
                     min_open=a.get("min_open"))
        if a.get("boarding"):
            brief["boarding_total"] = a["boarding"].get("total")
    if a.get("fee") is not None:
        brief["fee"] = a.get("fee")
    for k in ("level", "start", "end", "deadline", "hours"):
        if a.get(k) is not None:
            brief[k] = a.get(k)
    if a.get("schedule_text"):
        brief["schedule"] = a.get("schedule_text")
    if a.get("prereq_text"):
        brief["prereq"] = a.get("prereq_text")
    periods = engine.load_periods(db, domain_id)
    if periods:
        brief["periods"] = [
            {"name": p["name"], "start": p["attrs"].get("start"), "end": p["attrs"].get("end"),
             "enroll_deadline": p["attrs"].get("enroll_deadline"),
             "early_deadline": p["attrs"].get("early_deadline")}
            for p in periods]
    return brief


def _entity_cite_item(db, product: dict) -> dict | None:
    """单个班型/产品实体的出处条目:来源文档《标题》·章节 + 关键原文。"""
    pid = product.get("id")
    if not pid:
        return None
    row = db.execute(
        "SELECT d.title, d.filename, e.raw_excerpt FROM entities e "
        "JOIN documents d ON d.id=e.doc_id WHERE e.id=?", (pid,)).fetchone()
    src = ("《%s》" % (row["title"] or row["filename"])) if row else ""
    ch = product.get("chapter") or ""
    if not (src or ch):
        return None
    excerpt = search.key_excerpt(row["raw_excerpt"] or "") if row else ""
    excerpt = excerpt.rstrip(" |") if excerpt else ""
    return {"source": src, "chapter": ch, "excerpt": excerpt}


def _recommend_cite(db, candidates: list[dict]) -> list[dict]:
    """推荐结果的出处条目:各推荐班型来自的文档《标题》·章节,去重。
    实体级引用缺失时,回退到知识域规则级引用(_source_cite)。"""
    items, seen = [], set()
    for c in candidates:
        item = _entity_cite_item(db, c.get("product") or {})
        if item and (item["source"], item["chapter"]) not in seen:
            seen.add((item["source"], item["chapter"]))
            items.append(item)
    # 实体引用缺失时,回退到规则级引用
    if not items:
        for c in candidates:
            dom_id = c.get("_domain_id")
            if dom_id:
                for ci in _source_cite(db, dom_id):
                    key = (ci["source"], ci["chapter"])
                    if key not in seen:
                        seen.add(key)
                        items.append(ci)
                if items:
                    break
    return items


# ---------- 六个工具 ----------

def tool_welcome(role: str = "platform") -> dict:
    """欢迎语:优先 prompts/welcome_<role>.md,回退通用 welcome.md。"""
    text = config.get_prompt(f"welcome_{role}") or config.get_prompt("welcome")
    if not text:
        text = ("你好!我是AI课程顾问,可以为你提供:\n"
                "1. 学生课程(暑期AI素养夏令营)咨询与班型推荐\n"
                "2. 教师培训(AI素养培训体系)咨询与产品推荐\n"
                "3. 平台服务咨询\n"
                "请问你想了解哪方面?")
    return {"text": text, "role": role}


def tool_list_products(domain_ids: list[int] | None = None) -> dict:
    domain_ids = domain_ids or []
    products, discount_rules, cite = [], [], []
    seen = set()
    with get_db() as db:
        for dom_id in domain_ids:
            for p in engine.load_products(db, dom_id):
                products.append(product_brief(db, dom_id, p))
            discount_rules.extend(_discount_summary(db, dom_id))
            for c in _source_cite(db, dom_id):
                key = (c["source"], c["chapter"])
                if key not in seen:
                    seen.add(key)
                    cite.append(c)
        if not products:
            return {"products": [], "note": "所对接的知识域暂无班型数据。", "cite": cite}
        src_parts, source_note = [], ""
        for c in cite:
            s = c["source"] + ("·" + c["chapter"] if c["chapter"] else "")
            if s and s not in src_parts:
                src_parts.append(s)
        if src_parts:
            source_note = "— 出自 " + ";".join(src_parts)
    return {"products": products, "discount_rules": discount_rules,
            "source_note": source_note, "cite": cite}


def tool_recommend(city: str | None = None, date_start: str | None = None,
                   date_end: str | None = None, dates: list[str] | None = None,
                   mode: str | None = None, level: str | None = None,
                   days_off_continuous: bool | None = None, goal: str | None = None,
                   domain_ids: list[int] | None = None) -> dict:
    domain_ids = domain_ids or []
    cons = {"city": city, "date_start": date_start, "date_end": date_end,
            "dates": dates, "mode": mode, "level": level,
            "days_off_continuous": days_off_continuous, "goal": goal}
    candidates: list[dict] = []
    need: list[str] = []
    note = error = None
    cite: list[dict] = []
    with get_db() as db:
        for dom_id in domain_ids:
            res = engine.recommend(db, dom_id, cons)
            if res.get("error"):
                error = error or res["error"]
                continue
            for c in res.get("candidates", []):
                c.setdefault("domain", _domain_name(db, dom_id))
                c.setdefault("_domain_id", dom_id)  # 供 _recommend_cite 回退使用
                candidates.append(c)
            for n in res.get("need", []):
                if n not in need:
                    need.append(n)
            if res.get("note"):
                note = res["note"]
        if candidates:
            cite = _recommend_cite(db, candidates)
    if not candidates and not need and error:
        return {"candidates": [], "need": [], "error": error}
    return {"candidates": candidates, "need": need, "note": note, "cite": cite}


def tool_ask(question: str, product_hint: str | None = None,
             kb_ids: list[int] | None = None, domain_ids: list[int] | None = None) -> dict:
    """知识库问答。kb_ids 指定知识块引用范围,domain_ids 指定 ontology 精确匹配范围。"""
    domain_ids = domain_ids or []
    with get_db() as db:
        result = search.retrieve(db, domain_ids, question, product_hint=product_hint,
                                 top_k=config.top_k(), kb_ids=kb_ids)
        scope_desc = "、".join(_domain_source_label(db, d) for d in domain_ids) or "当前知识库"
    if not result["chunks"] and not result["facts"]:
        return {"answer": f"抱歉,我在{scope_desc}中没有找到与这个问题相关的资料,无法确认。"
                          f"如需帮助,{HUMAN_FALLBACK}。",
                "citations": [], "cite": [], "path_stats": result["path_stats"]}
    system = config.get_prompt("answer") or (
        "你是AI课程顾问的知识问答生成器。仅依据提供的参考资料作答,严禁编造;"
        "结构化事实中的数值必须原样采用;资料不足时明确回复无法确认;语言自然简洁。")
    system += (f"\n当前资料边界:{scope_desc}。不得引用边界外的信息;"
               f"涉及边界外范围的问题必须回答无法确认。")
    context = search.format_context(result)
    user = f"[参考资料]\n{context}\n\n[用户问题]\n{question}"
    msg = llm.chat([{"role": "system", "content": system},
                    {"role": "user", "content": user}])
    answer = (msg.content or "").strip() or "抱歉,暂时无法生成回答,请稍后重试。"
    citation = search.citation_note(result)
    return {"answer": answer + ("\n\n" + citation if citation else ""),
            "citation": citation,
            "citations": [{"doc": c["doc_name"], "chapter": c["chapter"]}
                          for c in result["chunks"][:3]],
            "cite": search.citation_items(result),
            "path_stats": result["path_stats"],
            "intent": result["rewrite"].get("intent")}


def tool_fee(product_name: str, payment_date: str, group_count: int = 1,
             boarding: bool = False, period_name: str | None = None,
             domain_ids: list[int] | None = None) -> dict:
    domain_ids = domain_ids or []
    with get_db() as db:
        hit = hit_dom = None
        for dom_id in domain_ids:
            p = engine.find_product(db, dom_id, name=product_name)
            if p:
                hit, hit_dom = p, dom_id
                break
        if not hit:
            available = []
            for dom_id in domain_ids:
                available.extend(p["name"] for p in engine.load_products(db, dom_id))
            return {"error": f"未找到班型「{product_name}」"
                    + ("(不在本通道对接的知识域内)" if not available else ""),
                    "available": available}
        period = engine.find_period(db, hit_dom, name=period_name) if period_name else (
            engine.load_periods(db, hit_dom) or [None])[0]
        breakdown = engine.calculate_fee(db, hit_dom, hit, payment_date=payment_date,
                                         period=period, group_count=group_count,
                                         boarding=boarding)
        discount_rules = _discount_summary(db, hit_dom)
        # 早鸟价金额提示:override 直接给各形式早鸟价;subtract 按 课程费−立减 推算各等级早鸟价
        early_prices = {}
        base = breakdown["base_fee"]
        for r in engine.load_rules(db, hit_dom, "early_bird"):
            value_by = r["params"].get("value_by") or {}
            if r["params"].get("mode") == "override":
                for k, v in value_by.items():
                    early_prices[k] = v
            elif r["params"].get("mode") == "subtract":
                for k, v in value_by.items():
                    early_prices[k] = base - float(v)
        return {"product": hit["name"],
                "period": period["name"] if period else None,
                "payment_date": payment_date,
                "discount_rules": discount_rules,
                "early_prices": early_prices,
                "source_note": _source_note(db, hit_dom),
                "cite": _source_cite(db, hit_dom), **breakdown}


def tool_capture_lead(name: str = "", phone: str = "", intent: str = "", note: str = "",
                      session_id: str = "", agent_role: str = "") -> dict:
    """采集用户报名意向与联系方式,转人工课程顾问跟进。
    仅采集用户主动提供的留资,绝不对外提供任何联系方式;不虚称余位/报名成功。"""
    if not (name.strip() or phone.strip()):
        return {"error": "请先请用户提供姓名或联系方式,再记录报名意向。"}
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO leads(session_id, agent_role, name, phone, intent, note, status) "
            "VALUES(?,?,?,?,?,?, 'pending')",
            (session_id, agent_role, name.strip(), phone.strip(), intent, note))
        lead_id = cur.lastrowid
    return {"ok": True, "lead_id": lead_id,
            "message": "报名意向已记录,人工课程顾问将尽快与用户联系。"
                       "请勿向用户承诺余位或报名结果。"}


def tool_enrollment(product_name: str | None = None,
                    domain_ids: list[int] | None = None) -> dict:
    domain_ids = domain_ids or []
    with get_db() as db:
        dom_id = domain_ids[0] if domain_ids else None
        product = None
        if product_name:
            for d in domain_ids:
                product = engine.find_product(db, d, name=product_name)
                if product:
                    dom_id = d
                    break
        if dom_id is None:
            return {"note": "当前未对接知识域。", "manual_fallback": HUMAN_FALLBACK}
        info = engine.enrollment_info(db, dom_id, product)
        # 出处:班型来源 + 知识域规则来源(退费/改期/前置等),去重
        cite, seen = [], set()
        if product:
            item = _entity_cite_item(db, product)
            if item and (item["source"], item["chapter"]) not in seen:
                seen.add((item["source"], item["chapter"]))
                cite.append(item)
        for c in _source_cite(db, dom_id):
            key = (c["source"], c["chapter"])
            if key not in seen:
                seen.add(key)
                cite.append(c)
        info["cite"] = cite
        return info


# ---------- Agent Skill(A级测试单:Function Calling 技能封装) ----------

def tool_course_detail(product_name: str | None = None,
                       domain_ids: list[int] | None = None) -> dict:
    """Skill-1 查询课程详情:按班型名称返回时间/地点/费用/师资/大纲(全部取自知识库)。
    降级:参数缺失返回 need 提示追问;班型不存在返回 available 列表供确认。"""
    domain_ids = domain_ids or []
    if not (product_name or "").strip():
        return {"error": "缺少班型名称参数", "need": ["请先告诉我你想查询哪个班型"]}
    name = product_name.strip()
    with get_db() as db:
        hit = hit_dom = None
        for dom_id in domain_ids:
            p = engine.find_product(db, dom_id, name=name)
            if p:
                hit, hit_dom = p, dom_id
                break
        if not hit:
            available = [p["name"] for d in domain_ids
                         for p in engine.load_products(db, d)]
            return {"error": f"未找到班型「{name}」",
                    "available": available,
                    "need": ["请确认班型名称,或从 available 列表中选择"]}
        detail = product_brief(db, hit_dom, hit)          # 时间/地点/费用/营期
        # 师资:teaches 链接(person → product)
        teachers = [r["name"] for r in db.execute(
            "SELECT e.name FROM relations r JOIN entities e ON e.id=r.src_id "
            "WHERE r.rel='teaches' AND r.dst_id=? AND e.type='person'", (hit["id"],))]
        # 大纲:该班型来源文档中含「大纲」的知识块摘录
        outline = ""
        row = db.execute("SELECT doc_id FROM entities WHERE id=?", (hit["id"],)).fetchone()
        if row:
            oc = db.execute(
                "SELECT chapter, content FROM knowledge_chunks "
                "WHERE doc_id=? AND (chapter LIKE '%大纲%' OR content LIKE '%大纲%') "
                "ORDER BY ord LIMIT 2", (row["doc_id"],)).fetchall()
            outline = " | ".join((c["chapter"] or "") + ":" + c["content"][:160]
                                 for c in oc)[:500]
        cite = []
        item = _entity_cite_item(db, hit)
        if item:
            cite.append(item)
        else:
            cite = _source_cite(db, hit_dom)
        return {"product": detail,
                "teachers": teachers,
                "outline": outline or "(资料中未收录该班型大纲,可换问课程安排)",
                "discount_rules": _discount_summary(db, hit_dom),
                "note": "费用为资料标准价;精确金额(含早鸟/团报)请再调用费用计算。",
                "cite": cite}


_TIME_PREF_MAP = (
    (("周末", "周六", "周日", "不能脱岗", "无法脱岗", "工作日上班"), {"days_off_continuous": False}),
    (("连续", "脱岗", "整周", "全天", "请假"), {"days_off_continuous": True}),
    (("线上", "远程", "在家", "不出门"), {"mode": "online"}),
    (("线下", "现场", "面授"), {"mode": "offline"}),
)


def _generic_recommend(db, domain_ids: list[int], cons: dict) -> list[dict]:
    """租户域通用推荐兜底(域内未配置 recommend 规则时):
    按城市/形式/时间偏好对班型做软过滤并生成理由;不改动引擎与官方规则。"""
    city, mode = cons.get("city"), cons.get("mode")
    days_off = cons.get("days_off_continuous")
    out = []
    for dom_id in domain_ids:
        for p in engine.load_products(db, dom_id):
            a = p["attrs"]
            hay = " ".join(str(x) for x in [p["name"], a.get("venue"), a.get("city"),
                                              a.get("format"), a.get("schedule_text")]
                           if x)
            reasons = []
            if city:
                if city in hay:
                    reasons.append(f"地点匹配「{city}」")
                else:
                    continue    # 城市硬约束:不匹配直接排除
            if mode == "online":
                if a.get("format") == "online" or "线上" in hay:
                    reasons.append("形式为线上,符合偏好")
                else:
                    continue
            elif mode == "offline":
                if a.get("format") in ("offline", "intensive", "weekend") or "线下" in hay:
                    reasons.append("形式为线下,符合偏好")
                else:
                    continue
            if days_off is False:
                if "周末" in hay or a.get("format") == "weekend":
                    reasons.append("周末开课,无需连续脱岗")
            elif days_off is True:
                if "集训" in hay or a.get("format") == "intensive":
                    reasons.append("连续授课安排,适合可脱岗学员")
            if not reasons:
                reasons.append("在当前知识域范围内综合匹配")
            out.append({"product": p, "periods": [], "reasons": reasons,
                        "_domain_id": dom_id})
    return out


def tool_recommend_course(city: str | None = None, time_preference: str | None = None,
                          domain_ids: list[int] | None = None) -> dict:
    """Skill-2 推荐适合班型:按城市+时间偏好返回最匹配的 1-2 个班型及推荐理由。
    降级:约束不足返回 need 列表,应先追问再推荐;域内无推荐规则时走通用软过滤兜底。"""
    domain_ids = domain_ids or []
    cons: dict = {"city": (city or "").strip() or None}
    pref = (time_preference or "").strip()
    for words, patch in _TIME_PREF_MAP:
        if any(w in pref for w in words):
            cons.update(patch)
            break
    if not cons.get("city") and not pref:
        return {"candidates": [],
                "need": ["你所在的城市?", "时间偏好(只有周末有空 / 可以连续安排 / 线上均可)?"],
                "note": "约束不足,请先追问城市和可用时间,再调用本技能。"}
    candidates: list[dict] = []
    need: list[str] = []
    note = error = None
    with get_db() as db:
        for dom_id in domain_ids:
            res = engine.recommend(db, dom_id, cons)
            if res.get("error"):
                error = error or res["error"]
                continue
            for c in res.get("candidates", []):
                c.setdefault("_domain_id", dom_id)
                candidates.append(c)
            for n in res.get("need", []):
                if n not in need:
                    need.append(n)
            if res.get("note"):
                note = res["note"]
        # 域内未配置推荐策略(新租户常见)→ 通用兜底
        if not candidates and not error:
            candidates = _generic_recommend(db, domain_ids, cons)
            need = []
            note = None
        # 城市无匹配等场景:给出说明而非空结果,引导调整约束(如改线上)
        if not candidates and not need and not error:
            if cons.get("city"):
                note = f"知识库中暂无「{cons['city']}」开设的班型;如接受线上形式," \
                       "可说明「想线上参加」,或联系机构课程顾问确认其他安排。"
            else:
                note = "当前约束下没有匹配的班型,请补充更多偏好。"
        cite = _recommend_cite(db, candidates) if candidates else []
    candidates = candidates[:2]       # 测试单口径:返回最匹配的 1-2 个
    if not candidates and not need and error:
        return {"candidates": [], "need": [], "error": error}
    return {"candidates": candidates, "need": need, "note": note,
            "constraints_used": {k: v for k, v in cons.items() if v is not None},
            "cite": cite}


SKILL_COURSE_DETAIL_TOOL = {"type": "function", "function": {
    "name": "get_course_detail",
    "description": "Skill·查询课程详情:根据班型名称返回该班型的完整信息"
                   "(时间、地点、费用、师资、大纲)。用户询问某个班型的具体情况时调用。",
    "parameters": {"type": "object", "properties": {
        "product_name": {"type": "string", "description": "班型名称,如「北京线下班」"}},
        "required": ["product_name"]}}}

SKILL_RECOMMEND_COURSE_TOOL = {"type": "function", "function": {
    "name": "recommend_course_type",
    "description": "Skill·推荐适合班型:根据用户的城市与时间偏好(如「我在上海」"
                   "「我只有周末有空」)返回最匹配的 1-2 个班型及推荐理由。",
    "parameters": {"type": "object", "properties": {
        "city": {"type": "string", "description": "用户所在城市,如「上海」"},
        "time_preference": {"type": "string",
                            "description": "时间偏好,如「只有周末有空」「可以连续脱岗」「想线上」"}},
        "required": []}}}

# Skill 自描述元数据(/api/skills 输出,供评审与文档查验)
SKILLS_META = [
    {"name": "get_course_detail", "title": "查询课程详情",
     "description": SKILL_COURSE_DETAIL_TOOL["function"]["description"],
     "parameters": SKILL_COURSE_DETAIL_TOOL["function"]["parameters"],
     "returns": {"product": "班型结构化信息(名称/形式/地点/标准费用/时间/营期)",
                 "teachers": "师资姓名列表", "outline": "课程大纲摘录",
                 "discount_rules": "适用的优惠规则(早鸟/团报/叠加)",
                 "cite": "引用溯源(文档《名称》·章节)"}},
    {"name": "recommend_course_type", "title": "推荐适合班型",
     "description": SKILL_RECOMMEND_COURSE_TOOL["function"]["description"],
     "parameters": SKILL_RECOMMEND_COURSE_TOOL["function"]["parameters"],
     "returns": {"candidates": "最匹配的 1-2 个班型及推荐理由(product/reasons)",
                 "need": "尚缺的约束(非空时应先追问)",
                 "cite": "引用溯源(文档《名称》·章节)"}},
]


# ---------- 工具表(OpenAI function calling / MCP 共用) ----------

TOOLS = [
    {"type": "function", "function": {
        "name": "ask_knowledge",
        "description": "基于知识库回答课程相关问题(大纲/师资/物资/日程/费用说明等)。"
                       "返回含引用的答案。涉及精确价格/日期时优先用 calculate_fee 或参考返回中的结构化事实。",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "用户问题(可结合上下文补全)"},
            "product_hint": {"type": "string", "description": "当前上下文班型名,可为空"}},
            "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "recommend_products",
        "description": "按约束推荐班型。学生场景需要城市/形式与日期;教师场景需要日期与是否连续脱岗。"
                       "约束不足时返回 need 列表,应先追问再推荐。",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"}, "date_start": {"type": "string"},
            "date_end": {"type": "string"},
            "dates": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["offline", "online", "any"]},
            "level": {"type": "string", "enum": ["L1", "L2", "L3"]},
            "days_off_continuous": {"type": "boolean"},
            "goal": {"type": "string"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "calculate_fee",
        "description": "确定性费用计算:课程费−唯一适用优惠+自愿食宿,返回逐项拆解。"
                       "用户问具体价格/早鸟/团报/食宿费用时调用。",
        "parameters": {"type": "object", "properties": {
            "product_name": {"type": "string"},
            "payment_date": {"type": "string", "description": "缴费日期 YYYY-MM-DD"},
            "group_count": {"type": "integer", "description": "团报人数,默认1"},
            "boarding": {"type": "boolean", "description": "是否选择食宿(仅部分线下班型)"},
            "period_name": {"type": "string", "description": "营期名(有营期的班型,默认第一期)"}},
            "required": ["product_name", "payment_date"]}}},
    {"type": "function", "function": {
        "name": "list_products",
        "description": "列出本通道知识域下全部真实班型/产品。用户要求「查看所有课程」或需要全景时调用。",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_enrollment_info",
        "description": "获取报名流程要点、报名截止、退费规则、改期与前置要求。",
        "parameters": {"type": "object", "properties": {
            "product_name": {"type": "string"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "set_session_context",
        "description": "记录当前会话上下文(用户身份、当前讨论的班型、已采集约束),"
                       "供多轮对话继承。每次明确身份或确定班型后调用。",
        "parameters": {"type": "object", "properties": {
            "identity": {"type": "string", "enum": ["student", "teacher", "org"]},
            "domain": {"type": "string"},
            "current_product": {"type": "string"},
            "constraints": {"type": "object"}},
            "required": []}}},
]

# 留资转人工工具(仅在智能体启用 lead_capture 能力时,由 loop/MCP 装配)
CAPTURE_LEAD_TOOL = {"type": "function", "function": {
    "name": "capture_lead",
    "description": "记录用户的报名意向与联系方式,转人工课程顾问跟进。"
                   "当用户明确表达报名意向、需要人工处理时调用;不得虚构余位/报名结果/联系方式。",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string", "description": "用户姓名/称呼"},
        "phone": {"type": "string", "description": "用户联系方式(电话或微信)"},
        "intent": {"type": "string", "description": "意向班型或诉求"},
        "note": {"type": "string", "description": "补充说明(用户其他需求)"}},
        "required": []}}}


_DISPATCH = {
    "ask_knowledge": lambda a: tool_ask(a["question"], a.get("product_hint"),
                                        a.get("kb_ids"), a.get("domain_ids")),
    "capture_lead": lambda a: tool_capture_lead(
        a.get("name", ""), a.get("phone", ""), a.get("intent", ""), a.get("note", ""),
        a.get("session_id", ""), a.get("agent_role", "")),
    "recommend_products": lambda a: tool_recommend(
        a.get("city"), a.get("date_start"), a.get("date_end"), a.get("dates"),
        a.get("mode"), a.get("level"), a.get("days_off_continuous"), a.get("goal"),
        domain_ids=a.get("domain_ids")),
    "calculate_fee": lambda a: tool_fee(
        a["product_name"], a["payment_date"],
        int(a.get("group_count", 1)), bool(a.get("boarding", False)), a.get("period_name"),
        domain_ids=a.get("domain_ids")),
    "list_products": lambda a: tool_list_products(domain_ids=a.get("domain_ids")),
    "get_enrollment_info": lambda a: tool_enrollment(a.get("product_name"),
                                                     domain_ids=a.get("domain_ids")),
    "get_course_detail": lambda a: tool_course_detail(a.get("product_name"),
                                                      domain_ids=a.get("domain_ids")),
    "recommend_course_type": lambda a: tool_recommend_course(
        a.get("city"), a.get("time_preference"), domain_ids=a.get("domain_ids")),
}


def dispatch(name: str, args: dict) -> dict:
    """工具统一入口;LLM 异常降级为"稍后重试",其他异常返回 error 字段。"""
    if name == "set_session_context":
        return {"ok": True}  # 会话侧单独处理状态写入
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": f"未知工具: {name}"}
    try:
        return fn(args or {})
    except llm.LLMError as e:
        log.warning("工具 %s 模型调用失败: %s", name, e)
        return {"error": "模型服务暂时不可用,请稍后重试。"}
    except Exception as e:  # noqa: BLE001
        log.exception("工具 %s 执行异常", name)
        return {"error": f"处理出现问题,请稍后重试。({type(e).__name__})"}
