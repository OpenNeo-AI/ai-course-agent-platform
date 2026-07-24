"""Ontology 抽取管线:文档 → 按章切分 → LLM 结构化抽取 → 跨章合并 → 候选入库。

抽取结果 status=extracted(候选),由 portal 确认/修正(M4);对同一 doc_id 重复抽取幂等。
通用机制:
- 跨章合并:同 (type, name) 实体深合并 attrs,先出现章节的非空值优先(如第三章的
  正确报名截止压住第五章的误标;第五章的费用补进第三章的班型);
- 合并后清洗:丢弃 attrs 全空的实体、缺关键属性的伪产品;
- 规则按 kind 去重(other 除外),保留最早出现的一条。
每素材可配抽取提示 hints:data/config/prompts/extract_hints_<code>.md(portal 可编辑)。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

from .. import config, llm

log = logging.getLogger(__name__)

_CHAPTER_RE = re.compile(r"^(第[一二三四五六七八九十百]+章\s*\S+|附录\s*\S+)")

# 产品实体至少应有这些属性之一,否则视为伪产品(项目名/泛指/物资清单等)
_PRODUCT_KEY_ATTRS = ("fee_standard", "fee", "venue", "scale", "start", "min_open")
_PERIOD_KEY_ATTRS = ("start", "end", "enroll_deadline", "early_deadline")
# 全局性规则:每种只保留最早出现的一条
_UNIQUE_RULE_KINDS = ("early_bird", "group_discount", "stack_policy", "fee_formula",
                      "refund", "prerequisite", "reschedule")


def split_chapters(text: str) -> list[tuple[str, str]]:
    """按「第X章 …/附录 …」标题切章;无标题的归入"前言"。"""
    chapters: list[tuple[str, str]] = []
    current_title, buf = "前言", []
    for line in text.splitlines():
        m = _CHAPTER_RE.match(line.strip())
        if m:
            if "".join(buf).strip():
                chapters.append((current_title, "\n".join(buf).strip()))
            current_title, buf = line.strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        chapters.append((current_title, "\n".join(buf).strip()))
    return chapters


def clear_document_ontology(db: sqlite3.Connection, doc_id: int) -> None:
    db.execute("DELETE FROM relations WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM entities WHERE doc_id=?", (doc_id,))
    db.execute("DELETE FROM rules WHERE doc_id=?", (doc_id,))


def _is_empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _deep_merge(base: dict, extra: dict) -> dict:
    """extra 并入 base:base 中已有的非空值优先;dict 递归合并。"""
    out = dict(base)
    for k, v in extra.items():
        if k not in out or _is_empty(out[k]):
            out[k] = v
        elif isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
    return out


def _merge_entities(raw: list[dict]) -> list[dict]:
    """同 (type, name) 跨章合并,随后清洗伪实体。保持首次出现顺序。"""
    merged: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for ent in raw:
        key = (ent.get("type", "other"), (ent.get("name") or "").strip())
        if not key[1]:
            continue
        if key in merged:
            m = merged[key]
            m["attrs"] = _deep_merge(m["attrs"], ent.get("attrs", {}))
            if ent.get("excerpt"):
                m["excerpt"] = (m["excerpt"] + " | " + ent["excerpt"])[:300]
        else:
            merged[key] = {"type": key[0], "name": key[1],
                           "attrs": ent.get("attrs", {}),
                           "chapter": ent.get("chapter", ""),
                           "excerpt": ent.get("excerpt", "")}
            order.append(key)

    result = []
    for key in order:
        ent = merged[key]
        attrs = ent["attrs"]
        if _is_empty(attrs):
            continue
        if ent["type"] == "product" and not any(
                not _is_empty(attrs.get(k)) for k in _PRODUCT_KEY_ATTRS):
            continue
        if ent["type"] == "period" and not any(
                not _is_empty(attrs.get(k)) for k in _PERIOD_KEY_ATTRS):
            continue
        result.append(ent)
    return result


def _dedup_rules(raw: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for rule in raw:
        kind = rule.get("kind", "other")
        if kind in _UNIQUE_RULE_KINDS:
            if kind in seen:
                continue
            seen.add(kind)
        out.append(rule)
    return out


def extract_chapter(domain_code: str, title: str, body: str) -> dict:
    schema = config.get_schema("extract") or {"type": "object"}
    system = config.get_prompt("extract") or "你是结构化知识抽取器,只输出 JSON。"
    hints = config.get_prompt("extract_hints") or config.get_prompt(f"extract_hints_{domain_code}")
    if hints:
        system += ("\n\n## 抽取要点(仅应用与本文档主题相符的部分,无相符小节时按通用规范抽取)"
                   f"\n{hints}")
    # 注入本体 Schema 的链接类型,约束 relations 的 rel 代码
    link_types = config.ontology_schema().get("link_types", {})
    if link_types:
        lines = [f"- {code}({info.get('label', '')}):{info.get('description', '')}"
                 for code, info in link_types.items()]
        system += ("\n\n## 关系抽取规范\nrelations 的 rel 必须从以下链接类型代码中选择,"
                   "且两端(src/dst)都必须是本次抽取出的实体名:\n" + "\n".join(lines))
    user = (f"以下是《{title}》章节的纯文本。"
            f"请抽取其中的实体、关系与规则。\n\n{body[:12000]}")
    return llm.extract_json(system, user, schema, name="extract")


def extract_document(db: sqlite3.Connection, doc_id: int, domain_id: int,
                     title: str, text: str) -> dict:
    """对整篇文档执行抽取:按章抽取 → 跨章合并 → 入库。返回统计。
    实体/规则经 doc_id 归属本文档(进而经 知识库→知识域 归属)。"""
    dom = db.execute("SELECT code FROM domains WHERE id=?", (domain_id,)).fetchone()
    domain_code = dom["code"] if dom else ""
    clear_document_ontology(db, doc_id)
    stats = {"chapters": 0, "entities": 0, "relations": 0, "rules": 0, "errors": []}

    raw_entities: list[dict] = []
    raw_relations: list[dict] = []
    raw_rules: list[dict] = []
    for chapter, body in split_chapters(text):
        if len(body) < 20:
            continue
        stats["chapters"] += 1
        try:
            out = extract_chapter(domain_code, chapter, body)
        except llm.LLMError as e:
            stats["errors"].append(f"{chapter}: {e}")
            log.error("抽取失败 %s: %s", chapter, e)
            continue
        for ent in out.get("entities", []):
            ent["chapter"] = chapter
            raw_entities.append(ent)
        for rule in out.get("rules", []):
            rule["chapter"] = chapter
            raw_rules.append(rule)
        raw_relations.extend(out.get("relations", []))

    entities = _merge_entities(raw_entities)
    rules = _dedup_rules(raw_rules)

    name_to_id: dict[str, int] = {}
    for ent in entities:
        cur = db.execute(
            "INSERT INTO entities(type, name, attrs_json, doc_id, chapter, raw_excerpt, status) "
            "VALUES(?,?,?,?,?,?, 'extracted')",
            (ent["type"], ent["name"],
             json.dumps(ent["attrs"], ensure_ascii=False),
             doc_id, ent["chapter"], ent["excerpt"] or None),
        )
        name_to_id[ent["name"]] = cur.lastrowid
        stats["entities"] += 1

    for rule in rules:
        db.execute(
            "INSERT INTO rules(kind, scope_json, params_json, doc_id, chapter, raw_excerpt, status) "
            "VALUES(?,?,?,?,?,?, 'extracted')",
            (rule.get("kind", "other"), "{}",
             json.dumps(rule.get("params", {}), ensure_ascii=False),
             doc_id, rule.get("chapter", ""), rule.get("excerpt")),
        )
        stats["rules"] += 1

    seen_rel: set[tuple[int, str, int]] = set()
    for rel in raw_relations:
        src, dst = name_to_id.get(rel.get("src")), name_to_id.get(rel.get("dst"))
        relname = rel.get("rel", "related")
        if src and dst and (src, relname, dst) not in seen_rel:
            seen_rel.add((src, relname, dst))
            db.execute(
                "INSERT INTO relations(src_id, rel, dst_id, doc_id, chapter) VALUES(?,?,?,?,?)",
                (src, relname, dst, doc_id, rel.get("chapter", "")),
            )
            stats["relations"] += 1

    db.execute("UPDATE documents SET status=? WHERE id=?",
               ("extracted" if not stats["errors"] else "failed", doc_id))
    return stats
