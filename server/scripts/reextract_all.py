"""按当前抽取器与本体 Schema 重新抽取所有已入库文档(幂等)。

用法:.venv/Scripts/python scripts/reextract_all.py [--domain domain-a]
从 data/uploads 读取各文档原件 → 解析 → 切块向量化 → 本体抽取(含类型化链接)
→ 重算派生链接。用于抽取提示词/Schema 升级后的全量刷新。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config                                # noqa: E402
from app.core.db import get_db                             # noqa: E402
from app.core.ingest.chunk import ingest_text              # noqa: E402
from app.core.ingest.parse import parse_upload             # noqa: E402
from app.core.ontology.graph import derive_links           # noqa: E402


def _find_original(kb_id: int, filename: str) -> Path | None:
    cands = [
        config.UPLOAD_DIR / f"kb{kb_id}_{filename}",
        config.UPLOAD_DIR / filename,
        config.BASE_DIR.parent / "doc" / filename,
    ]
    for c in cands:
        if c.exists():
            return c
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="", help="只重抽指定知识域(如 domain-a)")
    args = ap.parse_args()

    with get_db() as db:
        docs = db.execute(
            "SELECT d.id, d.filename, d.title, d.kb_id, k.domain_id, dm.code AS domain_code "
            "FROM documents d JOIN kbs k ON k.id=d.kb_id "
            "JOIN domains dm ON dm.id=k.domain_id ORDER BY d.id").fetchall()
        domains_touched: set[int] = set()
        for d in docs:
            if args.domain and d["domain_code"] != args.domain:
                continue
            src = _find_original(d["kb_id"], d["filename"])
            if src is None:
                print(f"[skip] {d['filename']}:未找到原件")
                continue
            data = src.read_bytes()
            text = parse_upload(src.name, data)
            stats = ingest_text(db, d["kb_id"], d["filename"],
                                d["title"] or d["filename"], text)
            ex = stats.get("extract") or {}
            print(f"[done] {d['filename']} 知识域{d['domain_code']} "
                  f"chunks={stats['chunks']} entities={ex.get('entities')} "
                  f"rules={ex.get('rules')} derived={stats.get('derived_links')} "
                  f"errors={len(ex.get('errors') or [])}")
            if d["domain_id"]:
                domains_touched.add(d["domain_id"])
        for dom_id in sorted(domains_touched):
            n = derive_links(db, dom_id)
            print(f"[derive] 知识域#{dom_id} 派生链接 {n}")


if __name__ == "__main__":
    main()
