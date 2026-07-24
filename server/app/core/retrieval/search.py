"""多路检索:query 结构化改写 → 三路并行召回 → RRF 融合 → rerank 重排 → top-k。

三路:① 改写子句的向量语义召回 ② FTS5(trigram 中文关键词)召回 ③ ontology 精确事实匹配。
知识域引用范围由调用方传入(domain_ids 知识域 + kb_ids 知识库):范围外的知识块不参与
召回;ontology 命中精确事实(价格/日期)时直接采用结构化数据,杜绝数字幻觉。
"""
from __future__ import annotations

import logging
import sqlite3

from .. import llm
from ..ontology import engine
from .rewrite import rewrite_query

log = logging.getLogger(__name__)

RRF_K = 60
RECALL_K = 40          # 单路召回量(范围过滤前)
RERANK_POOL = 12       # 进入 rerank 的候选量


def _domain_source_name(db: sqlite3.Connection, domain_id: int) -> str:
    """知识域的引用来源名:名下文档标题(《…》),无则用知识域名。"""
    rows = db.execute(
        "SELECT DISTINCT d.title FROM documents d JOIN kbs k ON k.id=d.kb_id "
        "WHERE k.domain_id=? AND d.title IS NOT NULL AND d.title<>'' ORDER BY d.id",
        (domain_id,)).fetchall()
    titles = [r["title"] for r in rows]
    if titles:
        return "《" + "》、《".join(titles) + "》"
    row = db.execute("SELECT name FROM domains WHERE id=?", (domain_id,)).fetchone()
    return row["name"] if row else f"知识域#{domain_id}"


def _product_fact_card(db: sqlite3.Connection, domain_id: int, product: dict,
                       source_name: str) -> dict:
    """产品结构化事实卡:字段按数据存在性输出,不分支。"""
    a = product["attrs"]
    parts = [f"{product['name']}(来源章节:{product['chapter']})"]
    if a.get("fee_standard") is not None:
        parts.append(f"标准课程费 {a.get('fee_standard')} 元/人")
    elif a.get("fee") is not None:
        parts.append(f"价格 {a.get('fee')} 元/人")
    if a.get("boarding"):
        b = a["boarding"]
        parts.append(f"食宿可选:住宿 {b.get('lodging')} 元 + 餐食 {b.get('meal_per_day')} 元/天×"
                     f"{b.get('meal_days')} 天,合计 {b.get('total')} 元")
    for k, label in (("venue", "地点"), ("scale", "规模"), ("min_open", "开班人数"),
                     ("level", "等级"), ("start", "开始"), ("end", "结束"),
                     ("hours", "课时"), ("deadline", "报名截止")):
        if a.get(k) is not None:
            parts.append(f"{label}:{a[k]}")
    if a.get("prereq_text"):
        parts.append(f"前置要求:{a['prereq_text']}")
    periods = engine.load_periods(db, domain_id)
    if periods:
        parts.append("营期:" + ";".join(
            f"{p['name']} {p['attrs'].get('start')}—{p['attrs'].get('end')}" for p in periods))
    return {"type": "product", "name": product["name"], "chapter": product["chapter"],
            "source_name": source_name,
            "summary": "\n".join(parts), "product_id": product["id"]}


def _ontology_facts(db: sqlite3.Connection, domain_ids: list[int], rewrite: dict,
                    product_hint: str | None) -> list[dict]:
    """ontology 精确匹配路径:在各知识域内命中产品实体/营期 → 结构化事实卡片。"""
    hint = product_hint or (rewrite or {}).get("product_hint") or ""
    facts: list[dict] = []
    for dom_id in domain_ids:
        source_name = _domain_source_name(db, dom_id)
        product = engine.find_product(db, dom_id, name=hint) if hint else None
        if product:
            facts.append(_product_fact_card(db, dom_id, product, source_name))
        if ("营期" in hint or (rewrite or {}).get("intent") == "schedule"):
            periods = engine.load_periods(db, dom_id)
            if periods:
                lines = [f"{p['name']}:{a.get('start')}—{a.get('end')}({a.get('weekdays', '')}),"
                         f"报名截止 {a.get('enroll_deadline')},早鸟截止 {a.get('early_deadline')}"
                         for p in periods for a in [p["attrs"]]]
                facts.append({"type": "periods", "name": "全部营期", "chapter": periods[0]["chapter"],
                              "source_name": source_name,
                              "summary": "\n".join(lines)})
    return facts


def retrieve(db: sqlite3.Connection, domain_ids: list[int], question: str,
             product_hint: str | None = None, top_k: int = 5,
             context_hint: str = "", kb_ids: list[int] | None = None) -> dict:
    """返回 {chunks, facts, rewrite, path_stats}。
    domain_ids:知识域范围(供 ontology 精确匹配);kb_ids:知识库范围(给定后知识块按
    kb_id 过滤,否则不过滤——用于通用 REST 入口)。"""
    rw = rewrite_query(question, context_hint)
    facts = _ontology_facts(db, domain_ids, rw, product_hint)

    # 路径①:向量召回
    vec_ids: list[tuple[int, float]] = []
    from .. import db as dbmod
    if dbmod.vec_available:
        q_text = " ".join((rw.get("sub_queries") or [question])[:3])
        try:
            vec = llm.embed([q_text])[0]
            vec_ids = dbmod.vec_search(db, vec, k=RECALL_K)
        except llm.LLMError as e:
            log.warning("向量召回跳过: %s", e)

    # 路径②:FTS 关键词召回
    fts_ids: list[tuple[int, float]] = []
    for kw in (rw.get("keywords") or [])[:5]:
        fts_ids.extend(dbmod.fts_search(db, kw, k=20))
    if not fts_ids:
        fts_ids = dbmod.fts_search(db, question[:60], k=20)

    # RRF 融合
    scores: dict[int, float] = {}
    for rank, (cid, _d) in enumerate(vec_ids):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, (cid, _s) in enumerate(fts_ids):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)

    chunks: list[dict] = []
    if scores:
        ph = ",".join("?" * len(scores))
        rows = db.execute(
            f"SELECT * FROM knowledge_chunks WHERE id IN ({ph})", list(scores.keys())
        ).fetchall()
        if kb_ids is not None:
            allowed = set(kb_ids)
            merged = [dict(r) | {"rrf": scores[r["id"]]} for r in rows if r["kb_id"] in allowed]
        else:
            merged = [dict(r) | {"rrf": scores[r["id"]]} for r in rows]
        merged.sort(key=lambda x: x["rrf"], reverse=True)
        pool = merged[:RERANK_POOL]

        # rerank 重排
        ranked = pool
        if len(pool) > 1:
            try:
                order = llm.rerank(question, [p["content"] for p in pool], top_n=top_k)
                ranked = [pool[idx] | {"score": sc} for idx, sc in order if idx < len(pool)]
            except llm.LLMError as e:
                log.warning("rerank 失败,按 RRF 序返回: %s", e)
                ranked = pool[:top_k]
        chunks = [{
            "id": p["id"], "doc_name": p["doc_name"], "chapter": p["chapter"],
            "content": p["content"], "score": p.get("score", p["rrf"]),
        } for p in ranked[:top_k]]

    return {
        "chunks": chunks,
        "facts": facts,
        "rewrite": rw,
        "path_stats": {"vec": len(vec_ids), "fts": len(fts_ids),
                       "facts": len(facts), "candidates": len(scores)},
    }


def format_context(result: dict) -> str:
    """把检索结果组装成喂给生成 LLM 的带标注上下文。"""
    blocks = []
    for f in result.get("facts", []):
        blocks.append(f"[结构化事实|{f.get('name')}|{f.get('chapter')}]\n{f['summary']}")
    for i, c in enumerate(result.get("chunks", []), 1):
        blocks.append(f"[资料片段{i}|《{c['doc_name']}》|{c['chapter']}]\n{c['content']}")
    return "\n\n".join(blocks)


def key_excerpt(text: str, lo: int = 20, hi: int = 30) -> str:
    """截取 20–30 字的关键原文语句(优先在句读处断句)。"""
    t = " ".join((text or "").split())
    if len(t) <= hi:
        return t
    head = t[:hi]
    idx = max((head.rfind(p, lo) for p in "。！？；，、 "), default=-1)
    return head[:idx + 1] if idx >= lo else head + "…"


def citation_items(result: dict) -> list[dict]:
    """结构化引用条目(与 citation_note 同源),供前端以卡片渲染;含关键原文语句。"""
    items, seen = [], set()
    for f in result.get("facts", []):
        src, ch = f.get("source_name") or "", f.get("chapter") or ""
        if (src or ch) and (src, ch) not in seen:
            seen.add((src, ch))
            items.append({"source": src, "chapter": ch,
                          "excerpt": key_excerpt(f.get("summary", ""))})
    for c in result.get("chunks", [])[:2]:
        src, ch = f"《{c['doc_name']}》", c.get("chapter") or ""
        if (src, ch) not in seen:
            seen.add((src, ch))
            items.append({"source": src, "chapter": ch,
                          "excerpt": key_excerpt(c.get("content", ""))})
    return items


def citation_note(result: dict) -> str:
    """生成回答末尾的引用标注(文档名/来源+章节)。"""
    refs = []
    for f in result.get("facts", []):
        src = f.get("source_name") or ""
        if f.get("chapter"):
            refs.append(f"{src}·{f['chapter']}" if src else f["chapter"])
    for c in result.get("chunks", [])[:2]:
        refs.append(f"《{c['doc_name']}》{c['chapter']}")
    seen, out = set(), []
    for r in refs:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return " — 出自 " + ";".join(out) if out else ""
