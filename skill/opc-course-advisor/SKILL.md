---
name: opc-course-advisor
description: AI课程顾问——学生夏令营班型咨询与推荐、教师培训(L1—L3)咨询与推荐、确定性费用计算(竞赛模拟环境,不编造事实)
metadata: {"openclaw":{"requires":{"bins":["python3"]}}}
---

# OPC AI课程顾问 Skill

把「AI课程顾问Agent」的核心能力接入当前 Agent 宿主。知识来自竞赛模拟资料:
素材A(学生夏令营)、素材B(教师培训);素材C(平台白皮书)暂未提供 → 平台问题答"无法确认"。

## 何时使用

用户询问以下内容时调用本 skill:
- 暑期AI素养夏令营:班型(北京线下班/上海线下班/线上直播班)、营期、费用、大纲、物资、报名
- 教师AI素养培训:L1—L3 暑期集训班/周末研修班、费用、前置要求、报名
- 费用计算:早鸟、团报、食宿(确定性计算,不会出错)

## 接入方式(二选一)

**方式一:MCP(推荐)** — 服务已暴露标准 MCP streamable HTTP 端点:
`http://<顾问服务地址>/mcp`,工具:get_welcome / list_products / recommend_products /
ask_knowledge / calculate_fee / get_enrollment_info。

**方式二:REST + 随附脚本**(宿主不支持 MCP 时):

```bash
python3 scripts/advisor.py ask --role student --question "北京线下班多少钱?"
python3 scripts/advisor.py fee --role student --product 北京线下班 --date 2026-07-10 --group 3
python3 scripts/advisor.py recommend --role student --city 北京 --mode offline --date-start 2026-08-01 --date-end 2026-08-07
python3 scripts/advisor.py recommend --role teacher --level L2 --days-off --date-start 2026-08-03 --date-end 2026-08-05
python3 scripts/advisor.py chat --role student --text "8月1日到7日有空,在北京,推荐哪个班?"
```

`--role` 指定作用域(student=学生知识域 / teacher=教师知识域 / platform=平台知识域,默认 platform)。
环境变量 `ADVISOR_BASE` 指定服务地址(默认 http://127.0.0.1:7000)。

## 行为约束(宿主 Agent 必须遵守)

1. 价格/日期/班型信息**只采用工具返回值**,不要自行补充或改写(包括班型名称——
   只有北京线下班/上海线下班/线上直播班与 L1/L2/L3 集训班/周末研修班,其余名称均为虚构)。
2. 资料无实时余位:不要声称满员、有余位、付款成功或报名完成。
3. 需要人工服务时统一回复"请联系模拟人工课程顾问"。
4. ask_knowledge 返回的引用标注("出自…")需保留给用户。
5. 推荐前先澄清用户身份(学生/教师)与关键约束;约束不足时按返回的 need 列表追问。
