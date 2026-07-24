#!/usr/bin/env python3
"""AI课程顾问 skill 辅助脚本:经 REST 调用顾问服务(无第三方依赖)。

环境变量 ADVISOR_BASE 指定服务地址(默认 http://127.0.0.1:7000)。
会话文件保存在 ~/.opc-advisor-session-<role>,供 chat 子命令多轮复用。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = os.environ.get("ADVISOR_BASE", "http://127.0.0.1:7000")
TIMEOUT = int(os.environ.get("ADVISOR_TIMEOUT", "180"))


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"无法连接顾问服务 {BASE}: {e}"}


def _tool(name: str, args: dict, role: str = "platform") -> dict:
    return _post("/api/tool", {"name": name, "args": args, "role": role})


def _session_file(role: str) -> Path:
    return Path.home() / f".opc-advisor-session-{role}"


def cmd_chat(args) -> dict:
    sf = _session_file(args.role)
    session_id = None
    if sf.exists() and not args.new:
        session_id = sf.read_text(encoding="utf-8").strip() or None
    if not session_id:
        s = _post("/api/session", {"role": args.role})
        session_id = s.get("session_id")
        if not session_id:
            return s
        sf.write_text(session_id, encoding="utf-8")
        if args.new:
            _post("/api/chat", {"session_id": session_id, "text": "重新开始"})
    # SSE:完整读取后解析最终回复
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps({"session_id": session_id, "text": args.text},
                        ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    reply, tools_used = "", []
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            buf = ""
            for raw in r.read().decode("utf-8").split("\n"):
                if raw.startswith("event:"):
                    ev = raw[6:].strip()
                elif raw.startswith("data:"):
                    data = raw[5:].strip()
                    if not data:
                        continue
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if ev == "delta":
                        reply += payload.get("text", "")
                    elif ev == "tool":
                        tools_used.append(payload.get("name", ""))
                    elif ev == "error":
                        return {"error": payload.get("error")}
    except Exception as e:  # noqa: BLE001
        return {"error": f"对话失败: {e}"}
    return {"reply": reply, "tools": tools_used, "session_id": session_id}


def main() -> int:
    p = argparse.ArgumentParser(description="AI课程顾问 skill CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chat", help="多轮对话")
    c.add_argument("--role", default="platform", choices=["student", "teacher", "platform"])
    c.add_argument("--text", required=True)
    c.add_argument("--new", action="store_true", help="新建会话(重置上下文)")

    a = sub.add_parser("ask", help="知识库问答")
    a.add_argument("--role", default="platform", choices=["student", "teacher", "platform"],
                   help="作用域:student=学生知识域,teacher=教师知识域,platform=平台知识域")
    a.add_argument("--question", required=True)
    a.add_argument("--product-hint", default="")

    f = sub.add_parser("fee", help="费用计算")
    f.add_argument("--role", default="platform", choices=["student", "teacher", "platform"])
    f.add_argument("--product", required=True)
    f.add_argument("--date", required=True, help="缴费日期 YYYY-MM-DD")
    f.add_argument("--group", type=int, default=1)
    f.add_argument("--boarding", action="store_true")
    f.add_argument("--period", default="")

    r = sub.add_parser("recommend", help="班型推荐")
    r.add_argument("--role", required=True, choices=["student", "teacher"])
    r.add_argument("--city", default="")
    r.add_argument("--date-start", default="")
    r.add_argument("--date-end", default="")
    r.add_argument("--mode", default="", choices=["", "offline", "online", "any"])
    r.add_argument("--level", default="", choices=["", "L1", "L2", "L3"])
    r.add_argument("--days-off", action="store_true", help="能连续脱岗(教师)")
    r.add_argument("--goal", default="")

    ls = sub.add_parser("products", help="列出班型")
    ls.add_argument("--role", default="platform", choices=["student", "teacher", "platform"])

    e = sub.add_parser("enrollment", help="报名要点")
    e.add_argument("--role", default="platform", choices=["student", "teacher", "platform"])
    e.add_argument("--product", default="")

    args = p.parse_args()
    if args.cmd == "chat":
        result = cmd_chat(args)
    elif args.cmd == "ask":
        result = _tool("ask_knowledge", {"question": args.question,
                                         "product_hint": args.product_hint}, role=args.role)
    elif args.cmd == "fee":
        result = _tool("calculate_fee", {"product_name": args.product,
                                         "payment_date": args.date, "group_count": args.group,
                                         "boarding": args.boarding, "period_name": args.period},
                       role=args.role)
    elif args.cmd == "recommend":
        result = _tool("recommend_products", {
            "city": args.city, "date_start": args.date_start,
            "date_end": args.date_end, "mode": args.mode, "level": args.level,
            "days_off_continuous": True if args.days_off else None, "goal": args.goal},
            role=args.role)
    elif args.cmd == "products":
        result = _tool("list_products", {}, role=args.role)
    else:
        result = _tool("get_enrollment_info", {"product_name": args.product}, role=args.role)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if "error" in result and not result.get("reply") else 0


if __name__ == "__main__":
    sys.exit(main())
