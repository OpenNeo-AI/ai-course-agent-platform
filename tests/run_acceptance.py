"""验收用例执行器:按 tests/acceptance_cases.yaml 逐案对话并断言,输出 Markdown 报告。

运行(server 目录下):
  .venv/Scripts/python ../tests/run_acceptance.py
报告:server/data/acceptance_report.md(可作"测试记录"交付物素材)。
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.agent import loop          # noqa: E402
from app.core import config, llm    # noqa: E402

CASES_FILE = ROOT / "tests" / "acceptance_cases.yaml"
REPORT_FILE = config.DATA_DIR / "acceptance_report.md"


def _norm(s: str) -> str:
    """归一化数字千分位分隔,避免"6,980"与"6980"造成的假失败。"""
    return s.replace(",", "").replace("，", "")


def _eval_turn(case: dict, turn: dict, reply: str, tools_used: list[str]) -> list[str]:
    """返回失败原因列表(空=通过)。"""
    fails = []
    reply_n = _norm(reply)
    for kw in turn.get("must", []):
        if _norm(kw) not in reply_n:
            fails.append(f"缺少关键词「{kw}」")
    for kw in turn.get("must_not", []):
        if _norm(kw) in reply_n:
            fails.append(f"出现禁止词「{kw}」")
    if turn.get("citation") and "出自" not in reply:
        fails.append("缺少引用标注(出自…)")
    need_tools = turn.get("tools")
    if need_tools:
        missing = [t for t in need_tools if t not in tools_used]
        if missing:
            fails.append(f"未调用工具 {missing}")
    if "min_len" in turn and len(reply) < turn["min_len"]:
        fails.append(f"回复过短({len(reply)} < {turn['min_len']})")
    return fails


def run_case(case: dict) -> dict:
    role = case.get("role", "platform")
    simulate = case.get("simulate_model_failure", False)
    sess = loop.new_session(role)
    sid = sess["session_id"]
    turn_logs = []
    case_fails = []
    tools_used: list[str] = []

    orig_chat, orig_stream = llm.chat, llm.chat_stream
    for i, turn in enumerate(case["turns"], 1):
        text = turn["text"]
        if text == "{long500}":
            text = "问题" * 251          # 502 字
        if simulate and i == len(case["turns"]):
            def boom(*a, **k):
                raise llm.LLMError("模拟模型服务失败")
            llm.chat = boom
            llm.chat_stream = boom      # 流式路径同样打桩
        try:
            r = loop.run_turn(sid, text)
        except Exception:               # noqa: BLE001
            turn_logs.append((text, f"[异常] {traceback.format_exc(limit=1)}", []))
            case_fails.append(f"第{i}轮抛出异常")
            break
        finally:
            if simulate:
                llm.chat, llm.chat_stream = orig_chat, orig_stream
        tools = [e["name"] for e in r["tool_events"]]
        tools_used.extend(tools)
        fails = _eval_turn(case, turn, r["reply"], tools_used)
        if fails:
            case_fails.extend(f"第{i}轮:{f}" for f in fails)
        turn_logs.append((text, r["reply"], tools))

    return {"name": case["name"], "category": case.get("category", ""),
            "passed": not case_fails, "fails": case_fails, "turns": turn_logs}


def main() -> int:
    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        res = run_case(case)
        status = "PASS" if res["passed"] else "FAIL"
        print(f"[{status}] {res['name']}" + (f"  <- {'; '.join(res['fails'])}" if res["fails"] else ""))
        results.append(res)

    passed = sum(1 for r in results if r["passed"])
    lines = [f"# 验收自测报告({datetime.now():%Y-%m-%d %H:%M})", "",
             f"用例总数:{len(results)},通过:{passed},失败:{len(results) - passed}", "",
             "| 用例 | 类别 | 结果 | 失败原因 |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['name']} | {r['category']} | {'通过' if r['passed'] else '失败'} | "
                     f"{'; '.join(r['fails']) or '—'} |")
    lines += ["", "## 对话明细", ""]
    for r in results:
        lines.append(f"### {r['name']}({'通过' if r['passed'] else '失败'})")
        for text, reply, tools in r["turns"]:
            shown = text if len(text) <= 60 else text[:60] + f"…({len(text)}字)"
            lines.append(f"- **用户**:{shown}" + (f"  [工具:{', '.join(tools)}]" if tools else ""))
            lines.append(f"- **顾问**:{reply[:600]}")
        lines.append("")
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{passed}/{len(results)} 通过,报告: {REPORT_FILE}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
