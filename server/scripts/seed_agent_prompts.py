"""为现有智能体填充默认系统提示词(幂等)。

按智能体名称匹配:学生课程顾问/教师培训顾问/平台服务顾问/AI 课程顾问。
仅当 prompt_text 为空时写入(不覆盖管理员已自定义的提示词)。

用法:  .venv/Scripts/python scripts/seed_agent_prompts.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.db import get_db  # noqa: E402
from scripts.reset_demo_data import AGENT_PROMPTS  # noqa: E402


def main() -> int:
    updated = 0
    with get_db() as db:
        for row in db.execute("SELECT id, name, config_json FROM tenant_agents").fetchall():
            prompt = AGENT_PROMPTS.get(row["name"])
            if not prompt:
                continue
            try:
                cfg = json.loads(row["config_json"] or "{}")
            except (ValueError, TypeError):
                cfg = {}
            if (cfg.get("prompt_text") or "").strip():
                continue  # 已自定义,跳过
            cfg["prompt_text"] = prompt
            db.execute("UPDATE tenant_agents SET config_json=? WHERE id=?",
                       (json.dumps(cfg, ensure_ascii=False), row["id"]))
            updated += 1
            print(f"  {row['name']}(id={row['id']}) 已填充提示词")
    print(f"完成:更新 {updated} 个智能体")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
