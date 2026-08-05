"""首次构建:摄入 doc/ 资料到对应知识域的知识库 → 知识块(向量+FTS)+ ontology 候选实体/规则。

用法(server 目录下):
  .venv/Scripts/python scripts/build_kb.py            # 摄入 + 抽取 + 种推荐策略 + 派生链接
  .venv/Scripts/python scripts/build_kb.py --no-extract   # 仅切块向量化
  .venv/Scripts/python scripts/build_kb.py --chunks-only-print  # 调试:只打印切块
需要 .env 的向量化/对话密钥。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config, db as dbmod  # noqa: E402
from app.core.ingest.chunk import chunk_text, ingest_text  # noqa: E402
from app.core.ingest.parse import parse_upload  # noqa: E402
from app.core.ontology import engine, graph  # noqa: E402

DOC_DIR = config.BASE_DIR.parent / "doc"
# (知识库 code, 源文件名, 文档标题) —— 知识库已按知识域预置(domain-a/b/c)
# .txt 为历史手工整理稿(未入库);仓库实际携带的是 doc/pdf/*.pdf,
# 故每条源允许多个候选文件名,按顺序取第一个存在的(见 _resolve_source)。
SOURCES = [
    ("kb-a", ["学生个人课程资料.txt", "pdf/学生个人课程资料.pdf"], "学生个人课程资料"),
    ("kb-b", ["教师个人培训资料.txt", "pdf/教师个人培训资料.pdf"], "教师个人培训资料"),
    ("kb-c", ["平台与企业服务资料.txt", "pdf/平台与企业服务资料.pdf"], "平台与企业服务资料"),
]


def _resolve_source(candidates: list[str]) -> Path | None:
    """返回第一个存在的候选源文件;全都不存在时返回 None。"""
    for name in candidates:
        path = DOC_DIR / name
        if path.exists():
            return path
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-extract", action="store_true", help="只切块向量化,不做 ontology 抽取")
    parser.add_argument("--chunks-only-print", action="store_true", help="只打印切块结果,不写库")
    parser.add_argument("--kb", default="", help="只构建指定知识库(kb-a/kb-b)")
    args = parser.parse_args()

    for kb_code, candidates, title in SOURCES:
        if args.kb and kb_code != args.kb:
            continue
        path = _resolve_source(candidates)
        if path is None:
            print(f"[skip] 未找到源文件(候选:{', '.join(candidates)})")
            continue
        fname = path.name
        # .txt 直接读;.pdf/.docx 走统一解析器(与 portal 上传同一条链路)
        if path.suffix.lower() == ".txt":
            text = path.read_text(encoding="utf-8")
        else:
            text = parse_upload(fname, path.read_bytes())

        if args.chunks_only_print:
            for chapter, ord_no, content in chunk_text(text):
                print(f"--- {kb_code} | {chapter} | #{ord_no} | {len(content)}字 ---")
                print(content[:120].replace("\n", " "), "…\n")
            continue

        # 全新环境(如 Docker 空数据卷)下 data/uploads 尚不存在;ensure_dirs 通常
        # 由 get_db() 触发,但这里的复制发生在首次连库之前,必须自行兜底。
        config.ensure_dirs()
        shutil.copy(path, config.UPLOAD_DIR / fname)
        with dbmod.get_db() as db:
            kb = db.execute("SELECT id FROM kbs WHERE code=?", (kb_code,)).fetchone()
            if not kb:
                print(f"[skip] 知识库 {kb_code} 不存在")
                continue
            stats = ingest_text(db, kb["id"], fname, title, text,
                                do_extract=not args.no_extract)
        print(f"[done] {kb_code} 《{title}》 chunks={stats['chunks']}")
        if stats["extract"]:
            ex = stats["extract"]
            print(f"       抽取: chapters={ex['chapters']} entities={ex['entities']} "
                  f"relations={ex['relations']} rules={ex['rules']} errors={len(ex['errors'])}")
            for err in ex["errors"]:
                print(f"       [error] {err}")

    # 种入推荐策略规则(数据化的推荐逻辑)并按知识域重算派生链接
    if not args.chunks_only_print:
        with dbmod.get_db() as db:
            engine.seed_recommend_rules(db)
            counts = graph.derive_all(db)
        print(f"[derive] 派生链接: {counts}")


if __name__ == "__main__":
    main()
