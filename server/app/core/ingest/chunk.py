"""知识摄入:章节切块 → 向量 → 写入 chunks/vec0/FTS;文档级幂等重建。"""
from __future__ import annotations

import logging
import sqlite3

from .. import config
from .. import db as dbmod
from .. import llm
from .extract import extract_document, split_chapters

log = logging.getLogger(__name__)

EMBED_BATCH = 20


def chunk_text(text: str) -> list[tuple[str, int, str]]:
    """(章节, 序号, 内容) 三元组列表;按章切分后段落累积至 ~chunk_size(.env 可调)。"""
    size, overlap = config.chunk_size(), config.chunk_overlap()
    result: list[tuple[str, int, str]] = []
    for chapter, body in split_chapters(text):
        buf, ord_no = "", 0
        for para in body.split("\n"):
            para = para.strip()
            if not para:
                continue
            if buf and len(buf) + len(para) > size:
                result.append((chapter, ord_no, buf.strip()))
                ord_no += 1
                buf = buf[-overlap:] + "\n" + para
            else:
                buf = buf + "\n" + para if buf else para
        if buf.strip() and len(buf.strip()) >= 12:
            result.append((chapter, ord_no, buf.strip()))
    return result


def clear_document_knowledge(db: sqlite3.Connection, doc_id: int) -> None:
    ids = [r["id"] for r in
           db.execute("SELECT id FROM knowledge_chunks WHERE doc_id=?", (doc_id,)).fetchall()]
    if not ids:
        return
    ph = ",".join("?" * len(ids))
    if dbmod.vec_available:
        try:
            db.execute(f"DELETE FROM chunks_vec WHERE rowid IN ({ph})", ids)
        except sqlite3.OperationalError as e:
            log.warning("清理 vec 失败(表可能不存在): %s", e)
    db.execute(f"DELETE FROM knowledge_chunks WHERE id IN ({ph})", ids)  # FTS 经触发器同步


def ingest_text(db: sqlite3.Connection, kb_id: int, filename: str,
                title: str, text: str, do_extract: bool = True) -> dict:
    """摄入一篇文档:documents 登记 → 切块向量化 → (可选)ontology 抽取。幂等。
    kb_id 指定归属知识库(必填),文档经 知识库→知识域 链路归属;是否产生结构化
    实体/规则由抽取结果决定(无相应内容的文档自然只有知识块,无结构化规则)。"""
    kb = db.execute("SELECT * FROM kbs WHERE id=?", (kb_id,)).fetchone()
    if not kb:
        raise ValueError(f"未知知识库 id: {kb_id}")
    domain_id = kb["domain_id"]

    old = db.execute("SELECT id FROM documents WHERE kb_id IS ? AND filename=?",
                     (kb_id, filename)).fetchone()
    if old:
        clear_document_knowledge(db, old["id"])
        db.execute("DELETE FROM relations WHERE doc_id=?", (old["id"],))
        db.execute("DELETE FROM entities WHERE doc_id=?", (old["id"],))
        db.execute("DELETE FROM rules WHERE doc_id=?", (old["id"],))
        db.execute("DELETE FROM documents WHERE id=?", (old["id"],))

    cur = db.execute(
        "INSERT INTO documents(kb_id, filename, title, status) "
        "VALUES(?,?,?, 'ingesting')",
        (kb_id, filename, title))
    doc_id = cur.lastrowid

    # 切块 + 向量化
    chunks = chunk_text(text)
    stats = {"chunks": len(chunks), "extract": None}
    if chunks:
        contents = [c[2] for c in chunks]
        vectors: list[list[float]] = []
        for i in range(0, len(contents), EMBED_BATCH):
            vectors.extend(llm.embed(contents[i:i + EMBED_BATCH]))
        dim = len(vectors[0])
        dbmod.ensure_vec_table(db, dim)
        import sqlite_vec
        for (chapter, ord_no, content), vec in zip(chunks, vectors):
            c = db.execute(
                "INSERT INTO knowledge_chunks(kb_id, doc_id, doc_name, chapter, ord, content) "
                "VALUES(?,?,?,?,?,?)",
                (kb_id, doc_id, title, chapter, ord_no, content))
            if dbmod.vec_available:
                db.execute("INSERT INTO chunks_vec(rowid, embedding) VALUES(?, ?)",
                           (c.lastrowid, sqlite_vec.serialize_float32(vec)))

    if do_extract:
        stats["extract"] = extract_document(db, doc_id, domain_id, title, text)
        # 抽取后按本体 Schema 重算该知识域的派生链接(归属/溯源/前置/变体/规则)
        try:
            from ..ontology.graph import derive_links
            stats["derived_links"] = derive_links(db, domain_id)
        except Exception as e:  # noqa: BLE001
            log.warning("派生链接计算失败: %s", e)
    db.execute("UPDATE documents SET status=? WHERE id=?",
               ("ready" if not (stats["extract"] or {}).get("errors") else "extract_failed", doc_id))
    return stats
