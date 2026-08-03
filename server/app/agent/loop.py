"""Agent 单轮会话循环:输入校验 → 会话控制 → function-calling 工具循环 → 持久化。

固定模板仅用于:欢迎语、菜单、重置、输入校验与错误提示(赛题允许);
课程事实回答一律经 tools(检索/引擎)生成。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date

from ..core import config, llm, tenancy, tools
from ..core.db import get_db
from ..core.scope import apply_scope_ask, scope_for_role
from . import session as sess

# 前端 extractCite 的后端等价实现:作为终极兜底，确保 done 事件永不为 cite:null
_CITE_RE = re.compile(r'[ \t>*_—–-]*出自[^\n]*')
_CITE_BODY_RE = re.compile(r'^[ \t>*_—–-]*出自[：:]?\s*')
_CITE_ITEM_RE = re.compile(r'^(《[^》]+》)\s*[·．.•]?\s*(.*)$')


def _parse_citations_from_text(text: str) -> list[dict]:
    """从回复文本中解析引用条目，与前端 extractCite+parseCiteLine 行为一致。
    作为工具未返回 cite 时的终极兜底。
    """
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for match in _CITE_RE.finditer(text):
        body = _CITE_BODY_RE.sub('', match.group())
        # 同时支持 ;；、 三种分隔符
        for part in re.split(r'[;;；、]\s*', body):
            p = part.strip().rstrip('*_')
            if not p:
                continue
            m = _CITE_ITEM_RE.match(p)
            if m:
                source = m.group(1)
                chapter = m.group(2).strip().rstrip('*_')
            else:
                source = p
                chapter = ''
            if source and (source, chapter) not in seen:
                seen.add((source, chapter))
                items.append({"source": source, "chapter": chapter})
    return items

log = logging.getLogger(__name__)

MAX_INPUT_LEN = 500
MAX_TOOL_ROUNDS = 6

RESET_WORDS = {"取消", "重来", "重新开始", "重置", "清空"}

REPLY_EMPTY = "请输入你想咨询的内容,例如「北京线下班多少钱」「L2集训班什么时候开课」。"
REPLY_TOO_LONG = f"输入内容超过{MAX_INPUT_LEN}字,请精简后再发送。"
REPLY_RESET = "会话已重置。"
REPLY_MODEL_ERROR = "模型服务暂时不可用,请稍后重试。"
REPLY_QUOTA_EXCEEDED = ("本月的免费对话额度已用完。升级到专业版可享无限对话、"
                        "知识库管理与数据看板,请前往套餐页升级。")
REPLY_SUB_REQUIRED = ("本机构的 AI 课程顾问服务尚未开通或订阅已到期。"
                      "请联系机构管理员登录管理工作台,选购套餐并完成支付后即可使用。")


def _system_prompt(role: str, state: dict, scope: dict) -> str:
    base = config.get_prompt(role) or config.get_prompt("platform") or "你是AI课程顾问。"
    state_block = json.dumps(state, ensure_ascii=False) if state else "{}"
    dom_desc = "、".join(d["name"] for d in scope["domains"]) or "(未对接)"
    scope_block = (f"\n\n## 引用范围(严格遵守)\n"
                   f"你只对接以下知识域:{dom_desc}。\n"
                   f"所有工具自动在这些知识域内检索与计算,不接受也无法指定范围外的内容。\n"
                   f"是否在范围内以工具检索结果为准:ask_knowledge 返回了相关资料就据实作答,"
                   f"不得以“话题看起来不属于某知识域”为由拒绝已检索到的内容;"
                   f"仅当工具未返回任何相关资料时,才回答“这不在我的参考资料范围内”,"
                   f"不编造、不越界作答,可引导用户去对应入口或联系人工。")
    return (f"{base}\n\n## 当前会话状态(JSON)\n{state_block}\n"
            f"## 今天日期\n{date.today().isoformat()}"
            f"(用户未说明缴费日期时,按今天计算早鸟资格){scope_block}")


def _is_reset(text: str) -> bool:
    t = text.strip()
    return t in RESET_WORDS or (len(t) <= 6 and any(w in t for w in RESET_WORDS))


def _reply_events(reply: str, state: dict, reset: bool, **done_extra):
    """固定模板回复(校验/重置/配额):整段作为一条 delta + done。"""
    yield {"type": "delta", "text": reply}
    yield {"type": "done", "state": state, "reset": reset, "cite": None, "cite_raw": None,
           **done_extra}


def run_turn_stream(session_id: str, text: str):
    """执行一轮对话,以生成器流式产出事件:
    {type: 'delta', text}   回答内容增量(LLM token 实时流)
    {type: 'tool', name, summary}  工具调用进度
    {type: 'done', state, reset, cite, cite_raw}  结束
    {type: 'error', error}  会话不存在等错误
    """
    with get_db() as db:
        s = sess.load_session(db, session_id)
    if not s:
        yield {"type": "error", "error": f"会话不存在: {session_id}"}
        return
    role, state = s["role"], s["state"]
    tenant_id = s.get("tenant_id")
    # 租户会话用租户知识域作用域;官方三通道保持 scope_for_role 原路径
    scope = tenancy.scope_for_tenant(tenant_id) if tenant_id else scope_for_role(role)

    stripped = (text or "").strip()
    if not stripped:
        yield from _reply_events(REPLY_EMPTY, state, False)
        return
    if len(stripped) > MAX_INPUT_LEN:
        yield from _reply_events(REPLY_TOO_LONG, state, False)
        return

    # 会话控制:重置(固定模板 + 欢迎语)
    if _is_reset(stripped):
        with get_db() as db:
            state = sess.reset_session(db, session_id)
            sess.append_message(db, session_id, "user", stripped)
            welcome = ((tenancy.tenant_welcome(db, tenant_id) if tenant_id else None)
                       or tools.tool_welcome(role)["text"])
            reply = f"{REPLY_RESET}\n\n{welcome}"
            sess.append_message(db, session_id, "assistant", reply)
        yield from _reply_events(reply, state, True)
        return

    # 租户门禁(官方三通道 tenant_id 为 NULL,不受影响):
    # ① 订阅须已开通(两档套餐均收费);② 配额检查(当前套餐均不限次,机制保留)
    if tenant_id:
        with get_db() as db:
            if not tenancy.is_active(db, tenant_id):
                sess.append_message(db, session_id, "user", stripped)
                sess.append_message(db, session_id, "assistant", REPLY_SUB_REQUIRED)
                yield from _reply_events(REPLY_SUB_REQUIRED, state, False,
                                         subscription_required=True,
                                         quota=tenancy.quota_state(db, tenant_id))
                return
            if not tenancy.quota_check(db, tenant_id):
                quota = tenancy.quota_state(db, tenant_id)
                sess.append_message(db, session_id, "user", stripped)
                sess.append_message(db, session_id, "assistant", REPLY_QUOTA_EXCEEDED)
                yield from _reply_events(REPLY_QUOTA_EXCEEDED, state, False,
                                         quota_exceeded=True, quota=quota)
                return
            tenancy.quota_inc(db, tenant_id)

    # 工具循环(流式):逐轮调用模型,内容 token 实时 yield,工具调用累积后执行
    messages = [{"role": "system", "content": _system_prompt(role, state, scope)}]
    with get_db() as db:
        messages.extend(sess.history(db, session_id, config.context_turns()))
    messages.append({"role": "user", "content": stripped})

    tool_events: list[dict] = []
    last_citation = ""
    last_source_note = ""
    _cite_items: list[dict] = []      # 合并所有工具的 cite 条目
    _cite_seen: set[tuple[str, str]] = set()
    recommended_names: list[str] = []
    reply_buf = ""            # 已流向用户的全部内容(用于兜底判断与持久化)
    got_final_turn = False
    # 按智能体能力装配工具:lead_capture 能力开启时纳入留资工具;
    # tenant_bot(租户会话)追加两个 Agent Skill——官方三通道工具集保持不变,验收零漂移
    caps = scope.get("capabilities") or {}
    tool_defs = list(tools.TOOLS)
    capture_tool = getattr(tools, "CAPTURE_LEAD_TOOL", None)
    if caps.get("lead_capture") and capture_tool:
        tool_defs = tool_defs + [capture_tool]
    if caps.get("tenant_bot"):
        tool_defs = tool_defs + [tools.SKILL_COURSE_DETAIL_TOOL,
                                 tools.SKILL_RECOMMEND_COURSE_TOOL]
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            content_acc = ""
            tc_buf: dict[int, dict] = {}
            calls: list[dict] = []
            # 本轮流式调用:尚无内容流出时允许重试(避免瞬时失败);已流出则不重试以免重复
            for attempt in range(3):
                content_acc = ""
                tc_buf = {}
                try:
                    for chunk in llm.chat_stream(messages, tools=tool_defs,
                                                 model=scope.get("model")):
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        piece = getattr(delta, "content", None)
                        if piece:
                            content_acc += piece
                            reply_buf += piece
                            yield {"type": "delta", "text": piece}
                        for tcd in (getattr(delta, "tool_calls", None) or []):
                            idx = getattr(tcd, "index", 0) or 0
                            slot = tc_buf.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if getattr(tcd, "id", None):
                                slot["id"] = tcd.id
                            fn = getattr(tcd, "function", None)
                            if fn:
                                if getattr(fn, "name", None):
                                    slot["name"] += fn.name
                                if getattr(fn, "arguments", None):
                                    slot["arguments"] += fn.arguments
                    calls = [tc_buf[i] for i in sorted(tc_buf)]
                    break
                except llm.LLMError:
                    if content_acc or attempt == 2:
                        raise
                    log.warning("会话 %s 流式第 %d 次失败,重试", session_id, attempt + 1)
                    time.sleep(1.5 * (attempt + 1))
            if not calls:
                got_final_turn = True
                break
            # 工具调用轮:登记 assistant 消息(含 tool_calls),逐个执行
            messages.append({"role": "assistant", "content": content_acc or None,
                             "tool_calls": [{"id": c["id"] or f"call_{i}", "type": "function",
                                             "function": {"name": c["name"], "arguments": c["arguments"]}}
                                            for i, c in enumerate(calls)]})
            for c in calls:
                name = c["name"]
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "set_session_context":
                    state = sess.update_state(session_id, args)
                    result = {"ok": True, "state": state}
                elif name == "ask_knowledge":
                    out = apply_scope_ask(scope, args)
                    result = out if "error" in out else tools.dispatch("ask_knowledge", out)
                elif name in ("recommend_products", "calculate_fee",
                              "list_products", "get_enrollment_info",
                              "get_course_detail", "recommend_course_type"):
                    args["domain_ids"] = scope["domain_ids"]
                    result = tools.dispatch(name, args)
                elif name == "capture_lead":
                    result = tools.dispatch(
                        "capture_lead", {**args, "session_id": session_id, "agent_role": role})
                else:
                    result = tools.dispatch(name, args)
                if name == "ask_knowledge" and result.get("citation"):
                    last_citation = result["citation"]
                if result.get("source_note"):
                    last_source_note = result["source_note"]
                # 合并所有工具的 cite(不覆盖,去重)
                for item in (result.get("cite") or []):
                    key = (item.get("source", ""), item.get("chapter", ""))
                    if key not in _cite_seen:
                        _cite_seen.add(key)
                        _cite_items.append(item)
                if name == "recommend_products":
                    for cand in result.get("candidates", []):
                        nm = (cand.get("product") or {}).get("name")
                        if nm and nm not in recommended_names:
                            recommended_names.append(nm)
                summary = _summarize(name, result)
                tool_events.append({"name": name, "args": args, "summary": summary})
                yield {"type": "tool", "name": name, "summary": summary}
                messages.append({"role": "tool",
                                 "tool_call_id": c["id"] or f"call_{len(messages)}",
                                 "content": json.dumps(result, ensure_ascii=False)[:6000]})
    except llm.LLMError as e:
        log.warning("会话 %s 模型失败: %s", session_id, e)

    # 无最终回答且未流出任何内容 → 模型失败兜底
    if not got_final_turn and not reply_buf.strip():
        reply_buf = REPLY_MODEL_ERROR
        yield {"type": "delta", "text": REPLY_MODEL_ERROR}

    # 推荐兜底:模型未说出推荐班型名时,追加推荐结论(流式补上)
    additions = ""
    if recommended_names and not any(n in reply_buf for n in recommended_names):
        additions += f"\n\n根据您的需求,为您推荐:{'、'.join(recommended_names)}。"
    # 引用兜底:模型改写工具答案丢失引用标注时,自动补回
    cite_raw = None
    # 工具作答但所有工具都没给出引用时,按对接知识域补一条归属引用
    if (not (last_citation or last_source_note) and tool_events
            and "出自" not in (reply_buf + additions)
            and reply_buf.strip() and reply_buf.strip() != REPLY_MODEL_ERROR):
        dom_names = "、".join(scope.get("domain_names") or [])
        if dom_names:
            last_source_note = f" — 出自{dom_names}知识库资料"
    if (last_citation or last_source_note) and "出自" not in (reply_buf + additions):
        cite_raw = last_citation or last_source_note
        additions += "\n\n" + cite_raw
    if additions:
        yield {"type": "delta", "text": additions}
    final = reply_buf + additions

    # 终极兜底:所有工具都没返回 cite 时,从回复文本解析引用
    cite_payload = _cite_items if _cite_items else _parse_citations_from_text(final)

    done_quota = None
    with get_db() as db:
        sess.append_message(db, session_id, "user", stripped)
        sess.append_message(db, session_id, "assistant", final,
                            tool_calls=[{"name": e["name"], "args": e["args"]}
                                        for e in tool_events] or None)
        if tenant_id:
            done_quota = tenancy.quota_state(db, tenant_id)
    yield {"type": "done", "state": state, "reset": False,
           "cite": cite_payload, "cite_raw": cite_raw, "quota": done_quota}


def run_turn(session_id: str, text: str) -> dict:
    """执行一轮对话(消费流式生成器),返回 {session_id, reply, tool_events, state, reset}。"""
    reply = ""
    tool_events: list[dict] = []
    done: dict = {}
    for ev in run_turn_stream(session_id, text):
        t = ev.get("type")
        if t == "delta":
            reply += ev["text"]
        elif t == "tool":
            tool_events.append({"name": ev["name"], "summary": ev["summary"]})
        elif t == "done":
            done = ev
        elif t == "error":
            raise ValueError(ev.get("error", "会话不存在"))
    return {"session_id": session_id, "reply": reply, "tool_events": tool_events,
            "state": done.get("state", {}), "reset": done.get("reset", False),
            "cite": done.get("cite"), "cite_raw": done.get("cite_raw")}


def _summarize(name: str, result: dict) -> str:
    """工具事件的一句话摘要(前端进度展示用)。"""
    if result.get("error"):
        return f"{name}: 出错了"
    if name == "ask_knowledge":
        stats = result.get("path_stats", {})
        return (f"知识检索完成(向量{stats.get('vec', 0)}/关键词{stats.get('fts', 0)}/"
                f"结构化事实{stats.get('facts', 0)})")
    if name == "recommend_products":
        n = len(result.get("candidates", []))
        return f"已按约束筛选出 {n} 个班型" if n else "正在确认约束条件"
    if name == "calculate_fee":
        return f"费用计算完成:合计 {result.get('total')} 元"
    if name == "list_products":
        return f"已取出 {len(result.get('products', []))} 个班型"
    if name == "get_enrollment_info":
        return "已取出报名要点"
    return name


def new_session(role: str = "platform", tenant_id: int | None = None) -> dict:
    s = sess.create_session(role, tenant_id=tenant_id)
    welcome = None
    if tenant_id:
        with get_db() as db:
            welcome = tenancy.tenant_welcome(db, tenant_id)
    return {**s, "welcome": welcome or tools.tool_welcome(role)["text"]}
