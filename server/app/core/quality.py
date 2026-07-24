"""对话质检:用 LLM 对会话按 准确性/规范性/体验 三维度评分,检测红线问题。

对应考题评分维度(知识准确与引用、功能与对话体验),用于智能体质量管理。
质检分 = 准确性*0.4 + 规范性*0.4 + 体验*0.2。仅对启用 quality_check 能力的智能体会话质检。
"""
from __future__ import annotations

import json
import logging
import sqlite3

from . import config, llm

log = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "accuracy": {"type": "number", "description": "准确性 0-100:回答是否基于资料、有无编造、事实是否正确"},
        "compliance": {"type": "number", "description": "规范性 0-100:是否遵守红线(人工话术/引用/不编造/边界/不虚称余位付款)"},
        "experience": {"type": "number", "description": "体验 0-100:多轮连贯、约束采集、表达清晰"},
        "issues": {"type": "array", "items": {"type": "string"}, "description": "发现的红线/质量问题"},
        "comment": {"type": "string", "description": "总体评语,一两句"},
    },
    "required": ["accuracy", "compliance", "experience"],
}


def check_session(db: sqlite3.Connection, session_id: str) -> dict:
    """对单个会话质检,写入 quality_checks,返回质检结果。"""
    sess = db.execute("SELECT role FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not sess:
        return {"error": "会话不存在"}
    role = sess["role"]
    msgs = db.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY id",
        (session_id,)).fetchall()
    turns = [m for m in msgs if m["content"] and m["role"] in ("user", "assistant")]
    if not any(m["role"] == "user" for m in turns):
        return {"error": "会话无用户提问,跳过质检"}
    conversation = "\n".join(
        f"{'用户' if m['role'] == 'user' else '顾问'}:{m['content']}" for m in turns)

    prompt = config.get_prompt("quality_check") or (
        "你是对话质检员。请对以下 AI 课程顾问与用户的对话,按三个维度打分(0-100):"
        "accuracy 准确性(基于资料、无编造、事实正确);compliance 规范性"
        "(遵守红线:人工话术『请联系人工课程顾问』、引用溯源、不编造、边界清晰、不虚称余位/付款);"
        "experience 体验(多轮连贯、约束采集、表达清晰)。并列出 issues(红线/质量问题)与 comment(总评)。")
    try:
        result = llm.extract_json(
            prompt,
            f"对话记录:\n{conversation[:8000]}",
            _SCHEMA, name="quality_check")
    except llm.LLMError:
        return {"error": "模型服务暂时不可用,请稍后重试"}

    def _num(v):
        try:
            return max(0, min(100, int(round(float(v)))))
        except (TypeError, ValueError):
            return 60

    acc, comp, exp = _num(result.get("accuracy")), _num(result.get("compliance")), _num(result.get("experience"))
    score = round(acc * 0.4 + comp * 0.4 + exp * 0.2)
    issues = result.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    comment = (result.get("comment") or "").strip()

    db.execute(
        "INSERT INTO quality_checks(session_id, agent_role, score, accuracy, compliance, "
        "experience, issues_json, comment) VALUES(?,?,?,?,?,?,?,?)",
        (session_id, role, score, acc, comp, exp,
         json.dumps(issues, ensure_ascii=False), comment))
    return {"session_id": session_id, "agent_role": role, "score": score,
            "accuracy": acc, "compliance": comp, "experience": exp,
            "issues": issues, "comment": comment}
