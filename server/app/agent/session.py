"""会话存取:SQLite 持久化,状态机字段集中在 state_json。

state: {identity, domain, current_product, constraints{...}}
role 为入口预设:student/teacher/platform(H5 路由决定)。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from ..core.db import get_db

ROLE_DEFAULTS = {
    "student": {"identity": "student", "domain": "domain-a"},
    "teacher": {"identity": "teacher", "domain": "domain-b"},
    "platform": {"identity": "org", "domain": "domain-c"},
}

_CST = timezone(timedelta(hours=8))  # 北京时间 UTC+8(不依赖服务器系统时区)


def _now() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def create_session(role: str = "platform", tenant_id: int | None = None,
                   agent_id: int | None = None) -> dict:
    sid = uuid.uuid4().hex[:12]
    state = dict(ROLE_DEFAULTS.get(role, {}))
    if role == "tenant":
        state = {"identity": "tenant"}
    with get_db() as db:
        db.execute("INSERT INTO sessions(id, role, state_json, updated_at, tenant_id, agent_id) "
                   "VALUES(?,?,?,?,?,?)",
                   (sid, role, json.dumps(state, ensure_ascii=False), _now(),
                    tenant_id, agent_id))
    return {"session_id": sid, "role": role, "state": state,
            "tenant_id": tenant_id, "agent_id": agent_id}


def load_session(db: sqlite3.Connection, session_id: str) -> dict | None:
    row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row:
        return None
    keys = row.keys()
    return {"session_id": row["id"], "role": row["role"],
            "state": json.loads(row["state_json"] or "{}"),
            "tenant_id": row["tenant_id"] if "tenant_id" in keys else None,
            "agent_id": row["agent_id"] if "agent_id" in keys else None}


def save_state(db: sqlite3.Connection, session_id: str, state: dict) -> None:
    db.execute("UPDATE sessions SET state_json=?, updated_at=? WHERE id=?",
               (json.dumps(state, ensure_ascii=False), _now(), session_id))


def reset_session(db: sqlite3.Connection, session_id: str) -> dict:
    """重置:清空状态与历史消息(赛题要求"清空上下文",重置后不引用旧班型)。"""
    row = db.execute("SELECT role FROM sessions WHERE id=?", (session_id,)).fetchone()
    role = row["role"] if row else "platform"
    state = dict(ROLE_DEFAULTS.get(role, {}))
    save_state(db, session_id, state)
    db.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    return state


def update_state(session_id: str, patch: dict) -> dict:
    with get_db() as db:
        sess = load_session(db, session_id)
        if not sess:
            raise ValueError(f"会话不存在: {session_id}")
        state = sess["state"]
        for k, v in (patch or {}).items():
            if k == "constraints" and isinstance(v, dict):
                state.setdefault("constraints", {}).update(v)
            elif v is not None:
                state[k] = v
        save_state(db, session_id, state)
        return state


def append_message(db: sqlite3.Connection, session_id: str, role: str,
                   content: str | None, tool_calls: list | None = None) -> None:
    db.execute(
        "INSERT INTO messages(session_id, role, content, tool_calls_json) VALUES(?,?,?,?)",
        (session_id, role, content,
         json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None))
    db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id))


def history(db: sqlite3.Connection, session_id: str, limit: int = 24) -> list[dict]:
    """最近的历史消息(按时间正序返回)。limit<=0 表示不限制(完整上下文)。"""
    sql = ("SELECT role, content FROM messages WHERE session_id=? AND role IN ('user','assistant') "
           "ORDER BY id DESC")
    args: list = [session_id]
    if limit and limit > 0:
        sql += " LIMIT ?"
        args.append(limit)
    rows = db.execute(sql, args).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
