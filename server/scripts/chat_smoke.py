"""端到端对话冒烟:学生通道 推荐→追问→费用→异常→重置。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import loop  # noqa: E402

s = loop.new_session("student")
sid = s["session_id"]
out = [f"session={sid} state={s['state']}\n"]

turns = [
    "孩子在北京,能线下参加,8月1日到7日有空,推荐哪个班?",
    "这个班什么时候上课?",
    "三个人一起报名,7月10日前缴费,总共多少钱?",
    "",                       # 空输入
    "x" * 600,                # 超长输入
    "重新开始",                # 重置
    "北京线下班多少钱?",        # 重置后不应引用旧班型上下文,但仍可正常回答
]

for t in turns:
    r = loop.run_turn(sid, t)
    out.append("USER : " + ((t[:50] + f"…({len(t)}字)") if len(t) > 50 else (t or "(空)")))
    out.append("TOOLS: " + str([e["name"] for e in r["tool_events"]]))
    out.append("STATE: " + str(r["state"]))
    out.append("REPLY: " + r["reply"][:500])
    out.append("=" * 60)

with open("data/chat_smoke.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("written data/chat_smoke.txt")
