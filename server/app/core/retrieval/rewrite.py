"""Query 结构化改写:原始问题 → 意图/实体/关键词/子查询/产品指向。"""
from __future__ import annotations

import logging

from .. import config, llm

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "sub_queries": {"type": "array", "items": {"type": "string"}},
        "product_hint": {"type": "string"},
        "fact_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "keywords", "sub_queries"],
}


def rewrite_query(question: str, context_hint: str = "") -> dict:
    """失败时降级为最小结构(原句作关键词),不阻断检索。"""
    fallback = {"intent": "other", "entities": [], "keywords": [question[:30]],
                "sub_queries": [question], "product_hint": "", "fact_fields": []}
    try:
        system = config.get_prompt("rewrite") or "把用户问题改写为结构化检索信息,只输出 JSON。"
        user = f"用户问题:{question}"
        if context_hint:
            user += f"\n当前对话上下文:{context_hint}"
        out = llm.extract_json(system, user, SCHEMA, name="rewrite")
        out.setdefault("product_hint", "")
        out.setdefault("fact_fields", [])
        if not out.get("sub_queries"):
            out["sub_queries"] = [question]
        if not out.get("keywords"):
            out["keywords"] = [question[:30]]
        return out
    except llm.LLMError as e:
        log.warning("query 改写失败,降级原句检索: %s", e)
        return fallback
