"""为现有智能体填充默认系统提示词与欢迎语(幂等)。

按智能体名称匹配:学生课程顾问/教师培训顾问/平台服务顾问/AI 课程顾问。
仅当对应字段为空时写入(不覆盖管理员已自定义的内容)。

用法:  .venv/Scripts/python scripts/seed_agent_prompts.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.db import get_db  # noqa: E402
from scripts.reset_demo_data import AGENT_PROMPTS, AGENT_WELCOMES  # noqa: E402


def main() -> int:
    updated = 0
    with get_db() as db:
        for row in db.execute("SELECT id, name, config_json FROM tenant_agents").fetchall():
            try:
                cfg = json.loads(row["config_json"] or "{}")
            except (ValueError, TypeError):
                cfg = {}
            changed = False
            prompt = AGENT_PROMPTS.get(row["name"])
            if prompt and not (cfg.get("prompt_text") or "").strip():
                cfg["prompt_text"] = prompt
                changed = True
            welcome = AGENT_WELCOMES.get(row["name"])
            if welcome and not (cfg.get("welcome_text") or "").strip():
                cfg["welcome_text"] = welcome
                changed = True
            if changed:
                db.execute("UPDATE tenant_agents SET config_json=? WHERE id=?",
                           (json.dumps(cfg, ensure_ascii=False), row["id"]))
                updated += 1
                print(f"  {row['name']}(id={row['id']}) 已填充提示词/欢迎语")
    print(f"完成:更新 {updated} 个智能体")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
