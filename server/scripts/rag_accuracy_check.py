"""RAG 准确率检测:跨三知识域事实问答 + 引用溯源断言,输出统计报告。

针对 A级测试单「RAG 准确率≥85%」指标:库内直接/间接问答、引用溯源、
库外拒答。用 demo1 的 3 个智能体(学生/教师/平台)实测。

用法: .venv/Scripts/python scripts/rag_accuracy_check.py [BASE_URL]
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7000"
ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "server" / "data" / "rag_accuracy_report.md"

# 每项: (智能体, 问题, 必含关键词[], 引用=True/False, 拒答期望词[])
CASES = [
    ("学生课程顾问", "北京线下班的标准课程费用是多少?", ["6980"], True, []),
    ("学生课程顾问", "早鸟价需要提前多少天缴费?提前缴费是多少钱?", ["21", "5980"], True, []),
    ("学生课程顾问", "学生夏令营第一期营期是什么时候?", ["8月1日"], True, []),
    ("学生课程顾问", "夏令营有哪几个班型?分别在哪些城市?", ["北京", "上海", "线上"], True, []),
    ("学生课程顾问", "三人一起报名有什么优惠?", ["3", "300"], True, []),
    ("教师培训顾问", "教师培训体系分为几个等级?", ["L1", "L2", "L3"], True, []),
    ("教师培训顾问", "教师不能连续脱岗时,适合报什么形式的培训?", ["周末", "研修"], True, []),
    ("教师培训顾问", "L3 等级需要什么前置条件?", ["前置", "L2"], True, []),
    ("平台服务顾问", "OPC 平台包含哪几个模块?", ["素养", "接单", "智脑", "社区"], True, []),
    ("平台服务顾问", "平台为机构或企业提供哪些服务?", ["合作", "培训"], True, []),
    ("学生课程顾问", "2027 年夏令营会涨价吗?", ["没有", "尚未", "未提及", "不在", "无法确认", "建议"], False, ["6980", "5980"]),
]


def req(path: str, body: dict | None = None, token: str = "", method: str = "POST"):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8")
                               if body is not None else None, headers=h, method=method)
    try:
        return json.loads(urllib.request.urlopen(r, timeout=180).read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "detail": e.read().decode("utf-8")[:200]}


def chat_reply(session_id: str, text: str) -> str:
    resp = urllib.request.urlopen(
        urllib.request.Request(BASE + "/api/chat",
                               data=json.dumps({"session_id": session_id, "text": text}).encode(),
                               headers={"Content-Type": "application/json"}), timeout=300)
    buf = resp.read().decode("utf-8").replace("\r\n", "\n")
    reply = ""
    for block in buf.split("\n\n"):
        lines = block.split("\n")
        ev = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("event")), "")
        data = "".join(l.split(":", 1)[1] for l in lines if l.startswith("data"))
        if ev == "delta":
            try:
                reply += json.loads(data)["text"]
            except Exception:  # noqa: BLE001
                pass
    return reply


def norm(text: str) -> str:
    return re.sub(r"[,\s，。、()（）]", "", text)


def main() -> int:
    login = req("/api/auth/login", {"username": "demo1", "password": "demo1234"})
    token = login.get("token")
    if not token:
        print("登录失败:", login.get("detail"))
        return 1
    agents = {a["name"]: a
              for a in req("/api/tenant/agents", token=token, method="GET").get("agents", [])}

    rows, passed = [], 0
    for name, question, must, need_cite, forbid in CASES:
        agent = agents.get(name)
        if not agent:
            rows.append((name, question, "未找到智能体", "—"))
            continue
        s = req("/api/session", {"agent": agent["slug"]})
        reply = chat_reply(s["session_id"], question)
        has_cite = "出自" in reply
        if forbid:
            ok = any(w in reply for w in must) and not any(w in norm(reply) for w in forbid)
            result = "通过(库外拒答)" if ok else "失败"
        else:
            ok = all(w in norm(reply) for w in must) and has_cite if need_cite \
                else all(w in norm(reply) for w in must)
            result = "通过" if ok else "失败"
        if ok:
            passed += 1
        rows.append((name, question, result, reply[:120].replace("\n", " ")))
        print(f"[{result}] {question}")

    total = len(CASES)
    rate = passed / total
    lines = [
        f"# RAG 准确率自测报告({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"- 测试环境:{BASE}",
        "- 测试方式:demo1 三个智能体(学生/教师/平台)跨知识域事实问答 + 引用溯源断言,",
        "  含 1 例库外拒答;必含关键词与「出自」引用由程序自动判定",
        f"- 结果:**{passed}/{total} 通过,准确率 {rate:.0%}**"
        f"({'达标(≥85%)' if rate >= 0.85 else '未达标'})",
        "",
        "| # | 智能体 | 问题 | 结果 | 回答摘要 |",
        "|---|--------|------|------|----------|",
    ]
    for i, (agent, q, result, brief) in enumerate(rows, 1):
        lines.append(f"| {i} | {agent} | {q} | {result} | {brief} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n准确率 {passed}/{total} = {rate:.0%};报告 → {REPORT}")
    return 0 if rate >= 0.85 else 2


if __name__ == "__main__":
    raise SystemExit(main())
