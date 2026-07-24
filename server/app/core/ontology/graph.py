"""本体图谱:派生链接计算、图数据组装、对象详情。

节点命名空间:e<entity_id> / r<rule_id> / d<document_id> / dom<domain_id>。
链接来源:relations(抽取的实体间关系)+ edges(派生链接 derived / 人工链接 manual),
均按知识域归属(domain_id)。派生链接(Palantir 式的接口语义):归属知识域、来源文档
溯源、等级前置链、同级班型变体、规则约束与优惠适用。
"""
from __future__ import annotations

import json
import logging
import sqlite3

from .. import config

log = logging.getLogger(__name__)

LEVEL_ORDER = ["L1", "L2", "L3", "L4", "L5"]


def _attrs(row) -> dict:
    try:
        return json.loads(row["attrs_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


# ---------- 派生链接 ----------

def derive_links(db: sqlite3.Connection, domain_id: int) -> int:
    """按 Schema 为某知识域重算派生链接(幂等)。返回写入条数。"""
    db.execute("DELETE FROM edges WHERE origin='derived' AND domain_id=?", (domain_id,))
    dom_node = f"dom{domain_id}"

    ents = db.execute(
        "SELECT e.* FROM entities e JOIN documents d ON d.id=e.doc_id "
        "JOIN kbs k ON k.id=d.kb_id WHERE k.domain_id=? ORDER BY e.id",
        (domain_id,)).fetchall()
    count = 0

    for e in ents:
        node = f"e{e['id']}"
        # 归属知识域
        db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                   "VALUES(?,?, 'belongs_to','derived',?)", (node, dom_node, domain_id))
        count += 1
        # 来源文档溯源
        if e["doc_id"]:
            db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                       "VALUES(?,?, 'sourced_from','derived',?)",
                       (node, f"d{e['doc_id']}", domain_id))
            count += 1

    products = [e for e in ents if e["type"] == "product"]

    # 等级前置链 L1→L2→L3
    by_level: dict[str, list] = {}
    for e in products:
        lv = (_attrs(e).get("level") or "").upper()
        if lv:
            by_level.setdefault(lv, []).append(e)
    for i in range(len(LEVEL_ORDER) - 1):
        lo, hi = LEVEL_ORDER[i], LEVEL_ORDER[i + 1]
        if lo in by_level and hi in by_level:
            for src in by_level[lo]:
                for dst in by_level[hi]:
                    db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                               "VALUES(?,?, 'prerequisite_of','derived',?)",
                               (f"e{src['id']}", f"e{dst['id']}", domain_id))
                    count += 1

    # 班型 × 营期 开设关系(每期同时开设全部班型,确定性派生;与抽取链接去重)
    period_ents = [e for e in ents if e["type"] == "period"]
    if period_ents and products:
        have = {(r["src_node"], r["dst_node"]) for r in db.execute(
            "SELECT src_node, dst_node FROM edges WHERE rel='runs_in' AND domain_id=?",
            (domain_id,))}
        have |= {(f"e{r['src_id']}", f"e{r['dst_id']}") for r in db.execute(
            "SELECT rel.src_id, rel.dst_id FROM relations rel "
            "JOIN entities s ON s.id=rel.src_id "
            "JOIN documents d ON d.id=s.doc_id JOIN kbs k ON k.id=d.kb_id "
            "WHERE rel.rel='runs_in' AND k.domain_id=?",
            (domain_id,))}
        for p in products:
            for pd in period_ents:
                key = (f"e{p['id']}", f"e{pd['id']}")
                if key not in have:
                    db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                               "VALUES(?,?, 'runs_in','derived',?)",
                               (key[0], key[1], domain_id))
                    count += 1

    # 同级变体:集训班 ↔ 周末研修班(单向存一条)
    for lv, group in by_level.items():
        intensive = [e for e in group if "集训" in e["name"]]
        weekend = [e for e in group if "周末" in e["name"] or "研修" in e["name"]]
        for a in intensive:
            for b in weekend:
                db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                           "VALUES(?,?, 'variant_of','derived',?)",
                           (f"e{a['id']}", f"e{b['id']}", domain_id))
                count += 1

    # 规则链接(推荐策略 recommend 为元规则,仅归属、不连产品)
    rules = db.execute(
        "SELECT r.* FROM rules r JOIN documents d ON d.id=r.doc_id "
        "JOIN kbs k ON k.id=d.kb_id WHERE k.domain_id=? ORDER BY r.id",
        (domain_id,)).fetchall()
    for r in rules:
        rnode = f"r{r['id']}"
        db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                   "VALUES(?,?, 'belongs_to','derived',?)", (rnode, dom_node, domain_id))
        count += 1
        kind = r["kind"]
        if kind in ("early_bird", "group_discount"):
            for e in products:
                db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                           "VALUES(?,?, 'discount_of','derived',?)",
                           (rnode, f"e{e['id']}", domain_id))
                count += 1
        elif kind == "prerequisite":
            try:
                levels = [x.upper() for x in json.loads(r["params_json"] or "{}").get("levels", [])]
            except json.JSONDecodeError:
                levels = []
            for e in products:
                if (_attrs(e).get("level") or "").upper() in levels:
                    db.execute("INSERT INTO edges(src_node,dst_node,rel,origin,domain_id) "
                               "VALUES(?,?, 'governed_by','derived',?)",
                               (rnode, f"e{e['id']}", domain_id))
                    count += 1
    return count


def derive_all(db: sqlite3.Connection) -> dict:
    dom_ids = {r["domain_id"] for r in db.execute(
        "SELECT DISTINCT k.domain_id AS domain_id FROM entities e "
        "JOIN documents d ON d.id=e.doc_id JOIN kbs k ON k.id=d.kb_id")}
    dom_ids |= {r["domain_id"] for r in db.execute(
        "SELECT DISTINCT k.domain_id AS domain_id FROM rules r "
        "JOIN documents d ON d.id=r.doc_id JOIN kbs k ON k.id=d.kb_id")}
    return {did: derive_links(db, did) for did in sorted(i for i in dom_ids if i)}


# ---------- 图组装 ----------

def _link_label(rel: str) -> str:
    lt = config.ontology_schema().get("link_types", {}).get(rel)
    return (lt or {}).get("label", rel)


def build_graph(db: sqlite3.Connection, domain_code: str | None = None,
                types: list[str] | None = None, q: str | None = None,
                limit: int = 800) -> dict:
    """组装图谱数据:{nodes, edges, stats}。domain 过滤知识域;types 过滤对象类型。"""
    domains = db.execute("SELECT * FROM domains ORDER BY id").fetchall()
    if domain_code:
        domains = [d for d in domains if d["code"] == domain_code]
    dom_ids = [d["id"] for d in domains]

    nodes: dict[str, dict] = {}
    for d in domains:
        nodes[f"dom{d['id']}"] = {
            "id": f"dom{d['id']}", "type": "domain", "label": d["name"],
            "status": "confirmed", "domain": d["code"],
            "props": {"code": d["code"], "description": d["description"]}}

    ent_rows = []
    rule_rows = []
    if dom_ids:
        ph = ",".join("?" * len(dom_ids))
        ent_rows = db.execute(
            "SELECT e.*, d2.filename AS doc_filename, k.domain_id AS dom_id "
            "FROM entities e JOIN documents d2 ON d2.id=e.doc_id "
            "JOIN kbs k ON k.id=d2.kb_id "
            f"WHERE k.domain_id IN ({ph}) ORDER BY e.id", dom_ids).fetchall()
        # 推荐策略(recommend)为元规则,不在图谱中作为节点展示
        rule_rows = db.execute(
            "SELECT r.*, k.domain_id AS dom_id FROM rules r "
            "JOIN documents d2 ON d2.id=r.doc_id JOIN kbs k ON k.id=d2.kb_id "
            f"WHERE k.domain_id IN ({ph}) AND r.kind<>'recommend' ORDER BY r.id",
            dom_ids).fetchall()

    dom_by_id = {d["id"]: d for d in domains}
    for e in ent_rows:
        nid = f"e{e['id']}"
        dom = dom_by_id.get(e["dom_id"])
        nodes[nid] = {
            "id": nid, "type": e["type"], "label": e["name"],
            "status": e["status"], "domain": dom["code"] if dom else None,
            "chapter": e["chapter"], "doc": e["doc_filename"],
            "props": _attrs(e)}
    for r in rule_rows:
        nid = f"r{r['id']}"
        dom = dom_by_id.get(r["dom_id"])
        try:
            params = json.loads(r["params_json"] or "{}")
        except json.JSONDecodeError:
            params = {}
        nodes[nid] = {
            "id": nid, "type": "rule", "label": r["kind"],
            "status": r["status"], "domain": dom["code"] if dom else None,
            "chapter": r["chapter"],
            "props": {"kind": r["kind"], **params}}

    # 链接:抽取关系(relations) + 统一链接表(edges)
    edges: list[dict] = []
    if dom_ids:
        if ent_rows:
            ent_ids = [e["id"] for e in ent_rows]
            ph2 = ",".join("?" * len(ent_ids))
            rel_rows = db.execute(
                "SELECT rel.id, rel.src_id, rel.rel, rel.dst_id, rel.chapter "
                "FROM relations rel "
                f"WHERE rel.src_id IN ({ph2}) AND rel.dst_id IN ({ph2})",
                ent_ids + ent_ids).fetchall()
            for row in rel_rows:
                edges.append({"id": f"rel{row['id']}", "source": f"e{row['src_id']}",
                              "target": f"e{row['dst_id']}", "type": row["rel"],
                              "label": _link_label(row["rel"]), "origin": "extracted"})
        ph = ",".join("?" * len(dom_ids))
        edg_rows = db.execute(
            f"SELECT * FROM edges WHERE domain_id IN ({ph}) ORDER BY id", dom_ids).fetchall()
        for row in edg_rows:
            edges.append({"id": f"edg{row['id']}", "source": row["src_node"],
                          "target": row["dst_node"], "type": row["rel"],
                          "label": _link_label(row["rel"]), "origin": row["origin"]})

    # 补齐边引用的文档节点
    doc_ids = {ed["target"][1:] for ed in edges
               if ed["target"].startswith("d")} | \
              {ed["source"][1:] for ed in edges if ed["source"].startswith("d")}
    if doc_ids:
        dph = ",".join("?" * len(doc_ids))
        for drow in db.execute(
                f"SELECT d.*, k.domain_id AS dom_id FROM documents d "
                f"JOIN kbs k ON k.id=d.kb_id WHERE d.id IN ({dph})",
                list(doc_ids)).fetchall():
            nid = f"d{drow['id']}"
            if nid not in nodes:
                dom = dom_by_id.get(drow["dom_id"])
                nodes[nid] = {
                    "id": nid, "type": "document", "label": drow["filename"],
                    "status": drow["status"], "domain": dom["code"] if dom else None,
                    "props": {"title": drow["title"], "status": drow["status"]}}

    node_list = list(nodes.values())
    # 图谱不展示知识域/知识文档节点(仅作组织与溯源,详情接口仍可访问);
    # 其关联边(归属/来源)因端点缺失在 included_ids 过滤中自动消失
    node_list = [n for n in node_list if n["type"] not in ("domain", "document")]
    if types:
        keep = set(types)
        node_list = [n for n in node_list if n["type"] in keep]
    if q:
        ql = q.strip().lower()
        node_list = [n for n in node_list if ql in (n["label"] or "").lower()]
    included_ids = {n["id"] for n in node_list}
    edge_list = [e for e in edges
                 if e["source"] in included_ids and e["target"] in included_ids]
    node_list = node_list[:limit]

    stats: dict[str, int] = {}
    for n in node_list:
        stats[n["type"]] = stats.get(n["type"], 0) + 1
    confirmed = sum(1 for n in node_list if n.get("status") == "confirmed")
    return {"nodes": node_list, "edges": edge_list,
            "stats": {"by_type": stats, "node_count": len(node_list),
                      "edge_count": len(edge_list), "confirmed": confirmed,
                      "dom_ids": sorted(dom_ids)}}


# ---------- 对象详情 ----------

def object_detail(db: sqlite3.Connection, node_id: str) -> dict | None:
    kind = idraw = None
    for p in ("dom", "e", "r", "d"):
        if node_id.startswith(p) and node_id[len(p):].isdigit():
            kind, idraw = p, node_id[len(p):]
            break
    if kind is None:
        return None
    oid = int(idraw)

    if kind == "e":
        row = db.execute(
            "SELECT e.*, d2.filename AS doc_filename, dm.name AS domain_name "
            "FROM entities e JOIN documents d2 ON d2.id=e.doc_id "
            "JOIN kbs k ON k.id=d2.kb_id JOIN domains dm ON dm.id=k.domain_id "
            "WHERE e.id=?", (oid,)).fetchone()
        if not row:
            return None
        obj = {"id": node_id, "type": row["type"], "label": row["name"],
               "status": row["status"], "domain_name": row["domain_name"],
               "chapter": row["chapter"], "doc": row["doc_filename"],
               "excerpt": row["raw_excerpt"], "props": _attrs(row)}
    elif kind == "r":
        row = db.execute(
            "SELECT r.*, dm.name AS domain_name FROM rules r "
            "JOIN documents d2 ON d2.id=r.doc_id JOIN kbs k ON k.id=d2.kb_id "
            "JOIN domains dm ON dm.id=k.domain_id WHERE r.id=?", (oid,)).fetchone()
        if not row:
            return None
        try:
            params = json.loads(row["params_json"] or "{}")
        except json.JSONDecodeError:
            params = {}
        obj = {"id": node_id, "type": "rule", "label": row["kind"],
               "status": row["status"], "domain_name": row["domain_name"],
               "chapter": row["chapter"], "excerpt": row["raw_excerpt"],
               "props": {"kind": row["kind"], **params}}
    elif kind == "d":
        row = db.execute(
            "SELECT d.*, dm.name AS domain_name FROM documents d "
            "JOIN kbs k ON k.id=d.kb_id JOIN domains dm ON dm.id=k.domain_id "
            "WHERE d.id=?", (oid,)).fetchone()
        if not row:
            return None
        obj = {"id": node_id, "type": "document", "label": row["filename"],
               "status": row["status"], "domain_name": row["domain_name"],
               "props": {"title": row["title"]}}
    elif kind == "dom":
        row = db.execute("SELECT * FROM domains WHERE id=?", (oid,)).fetchone()
        if not row:
            return None
        obj = {"id": node_id, "type": "domain", "label": row["name"],
               "status": "confirmed", "domain_name": row["name"],
               "props": {"code": row["code"], "description": row["description"]}}
    else:
        return None

    # 链接:relations(实体间抽取)+ edges(派生/人工)
    links = []
    if kind == "e":
        for row in db.execute(
                "SELECT rel.id, rel.rel, rel.chapter, 'out' AS dir, t.id AS oid, t.type AS otype, t.name AS oname "
                "FROM relations rel JOIN entities t ON t.id=rel.dst_id WHERE rel.src_id=? "
                "UNION ALL "
                "SELECT rel.id, rel.rel, rel.chapter, 'in', s.id, s.type, s.name "
                "FROM relations rel JOIN entities s ON s.id=rel.src_id WHERE rel.dst_id=?",
                (oid, oid)).fetchall():
            links.append({"edge_id": f"rel{row['id']}", "direction": row["dir"],
                          "rel": row["rel"], "rel_label": _link_label(row["rel"]),
                          "origin": "extracted", "chapter": row["chapter"],
                          "other": {"id": f"e{row['oid']}", "type": row["otype"],
                                    "label": row["oname"]}})
    for row in db.execute(
            "SELECT id, src_node, dst_node, rel, origin, note FROM edges "
            "WHERE src_node=? OR dst_node=? ORDER BY id", (node_id, node_id)).fetchall():
        # 归属(→知识域)/来源(→文档)为组织性链接,知识域与文档不作为图谱对象展示,
        # 其溯源信息已在对象详情的所属知识域/文档字段中体现,此处不再列出
        if row["rel"] in ("belongs_to", "sourced_from"):
            continue
        outgoing = row["src_node"] == node_id
        other_id = row["dst_node"] if outgoing else row["src_node"]
        links.append({"edge_id": f"edg{row['id']}",
                      "direction": "out" if outgoing else "in",
                      "rel": row["rel"], "rel_label": _link_label(row["rel"]),
                      "origin": row["origin"], "note": row["note"],
                      "other": _brief_node(db, other_id)})
    obj["links"] = links
    return obj


def _brief_node(db: sqlite3.Connection, node_id: str) -> dict:
    for p in ("dom", "e", "r", "d"):
        if node_id.startswith(p) and node_id[len(p):].isdigit():
            oid = int(node_id[len(p):])
            if p == "e":
                row = db.execute("SELECT type, name FROM entities WHERE id=?", (oid,)).fetchone()
                return {"id": node_id, "type": row["type"], "label": row["name"]} if row else {"id": node_id, "type": "?", "label": "?"}
            if p == "r":
                row = db.execute("SELECT kind FROM rules WHERE id=?", (oid,)).fetchone()
                return {"id": node_id, "type": "rule", "label": row["kind"]} if row else {"id": node_id, "type": "?", "label": "?"}
            if p == "d":
                row = db.execute("SELECT filename FROM documents WHERE id=?", (oid,)).fetchone()
                return {"id": node_id, "type": "document", "label": row["filename"]} if row else {"id": node_id, "type": "?", "label": "?"}
            if p == "dom":
                row = db.execute("SELECT name FROM domains WHERE id=?", (oid,)).fetchone()
                return {"id": node_id, "type": "domain", "label": row["name"]} if row else {"id": node_id, "type": "?", "label": "?"}
    return {"id": node_id, "type": "?", "label": node_id}
