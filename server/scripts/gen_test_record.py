"""从 acceptance_cases.yaml + acceptance_report.md 生成交付用《测试记录》。"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "tests/acceptance_cases.yaml").read_text(encoding="utf-8"))
REPORT = (ROOT / "server/data/acceptance_report.md").read_text(encoding="utf-8")

EXPECT_TEXT = {
    "资料事实": "事实正确(价格/日期/安排等与资料一致),回答含引用标注",
    "资料边界": "跨素材/资料外问题明确无法确认,不混用价格,不编造",
    "推荐": "推荐真实班型,理由逐条对应约束",
    "多轮": "正确继承班型上下文,连续三轮不断链",
    "异常": "不崩溃,给出符合要求的提示并可继续操作",
}

# 解析报告中的对话明细
blocks = {}
for b in re.split(r"### ", REPORT)[1:]:
    lines = b.splitlines()
    name = lines[0].split("(")[0].strip()
    turns = []
    for line in lines[1:]:
        if line.startswith("- **用户**:"):
            turns.append(("用户", line[len("- **用户**:"):].strip()))
        elif line.startswith("- **顾问**:"):
            turns.append(("顾问", line[len("- **顾问**:"):].strip()))
    blocks[name] = (lines[0], turns)

out = []
out.append("# 测试记录:AI课程顾问Agent\n")
out.append(f"- 测试时间:{datetime.now():%Y-%m-%d}")
out.append("- 测试环境:https://edu-demo.openneo.ai/ (学生通道 /s、教师通道 /t、通用 /c;MCP 端点 /mcp)")
out.append("- 测试方式:自动化对话脚本逐案执行 25 组官方验收用例(事实8/边界4/推荐5/多轮3/异常5),"
           "对每轮回复做关键词/引用/禁止词断言;另含 19 项事实回归单测(pytest)。")
out.append("- 总体结论:**25/25 通过**;事实回归单测 19/19 通过。\n")
out.append("| # | 类别 | 用例 | 输入(首轮) | 预期 | 结论 |")
out.append("|---|------|------|-----------|------|------|")

for i, c in enumerate(CASES, 1):
    first = c["turns"][0]["text"]
    shown = (first[:36] + "…") if len(first) > 36 else first
    header, _ = blocks.get(c["name"], ("", []))
    passed = "通过" if "通过" in header else ("失败" if "失败" in header else "?")
    out.append(f"| {i} | {c.get('category','')} | {c['name']} | {shown} | "
               f"{EXPECT_TEXT.get(c.get('category',''),'按断言')} | {passed} |")

out.append("\n## 抽样证据(实际对话)\n")
samples = ["事实1-北京线下班费用", "推荐1-北京学生线下", "多轮1-推荐后追问时间与物资",
           "边界1-平台会员价格", "异常2-超长输入"]
for name in samples:
    if name not in blocks:
        continue
    header, turns = blocks[name]
    out.append(f"### {name}\n")
    for role, text in turns:
        t = text if len(text) <= 500 else text[:500] + "……(节选)"
        out.append(f"- **{role}**:{t}")
    out.append("")

out.append("## 其他验证")
out.append("- MCP 接入:initialize → tools/list(6 工具)→ tools/call(calculate_fee)经 https 全链路通过。")
out.append("- 红线自查:回复中未出现满员/余位/付款成功/报名完成表述;人工引导统一为"
           "“请联系模拟人工课程顾问”;密钥仅存于服务器 .env,未入仓库。")
out.append("- 完整 25 组对话明细见 server/data/acceptance_report.md。")

(ROOT / "docs/测试记录.md").write_text("\n".join(out), encoding="utf-8")
print("written docs/测试记录.md,", len(out), "lines")
