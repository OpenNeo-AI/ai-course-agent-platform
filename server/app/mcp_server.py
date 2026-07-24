"""MCP server:每个智能体一个独立 MCP 端点,工具严格按其知识域作用域收敛。

端点(streamable HTTP,由 main.py 挂载):
  /mcp          通用课程顾问(对接全部知识域,含身份分流)
  /mcp/student  学生课程顾问(仅学生知识域)
  /mcp/teacher  教师培训顾问(仅教师知识域)

stdio 模式(本地宿主直连):
  python -m app.mcp_server [stdio] [platform|student|teacher]

工具实现与 Agent 会话循环同源(app/core/tools.py + app/core/scope.py),行为一致;
作用域随 portal 的知识域对接配置(agents.yaml)热变化,无需重启。
"""
from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .core import tools
from .core.scope import apply_scope_ask, scope_for_role

_ALLOWED_HOSTS = ["edu-demo.openneo.ai", "edu-demo.openneo.ai:*",
                  "3.39.24.74", "3.39.24.74:*",
                  "127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]:*"]
_ALLOWED_ORIGINS = ["https://edu-demo.openneo.ai", "http://edu-demo.openneo.ai",
                    "http://3.39.24.74", "https://3.39.24.74",
                    "http://127.0.0.1:*", "http://localhost:*", "https://127.0.0.1:*"]

INSTRUCTIONS = {
    "student": (
        "学生课程顾问 MCP。仅对接学生知识域:暑期AI素养夏令营"
        "(北京线下班/上海线下班/线上直播班)。所有事实来自知识库与结构化规则引擎,不编造;"
        "无实时余位数据,不得声称满员/余位/付款成功;需人工服务时引导“请联系人工课程顾问”。"
        "范围外问题(教师培训/平台会员等)会被工具拒绝,请如实转述。"
        "推荐前先采集约束(城市/日期/线上线下偏好);费用用 calculate_fee(确定性)。"),
    "teacher": (
        "教师培训顾问 MCP。仅对接教师知识域:初高中教师AI素养培训体系"
        "(L1—L3 暑期集训班/周末研修班)。所有事实来自知识库与结构化规则引擎,不编造;"
        "无实时余位数据,不得声称满员/余位/付款成功;需人工服务时引导“请联系人工课程顾问”。"
        "范围外问题(学生营期/平台会员等)会被工具拒绝,请如实转述。"
        "推荐前先采集约束(等级目标/日期/是否连续脱岗);L2/L3 需提示前置要求;"
        "费用用 calculate_fee(确定性)。"),
    "platform": (
        "平台智能体 MCP。面向机构/企业用户,提供机构合作与平台服务咨询(对接平台服务知识域)。"
        "所有事实来自知识库与结构化规则引擎,不编造;平台资料暂未提供时如实回答“无法确认”;"
        "无实时余位数据,不得声称满员/余位/付款成功;需人工服务时引导“请联系人工课程顾问”。"
        "个人课程/培训咨询请引导学生或教师入口。"),
}


def build_mcp(role: str) -> FastMCP:
    """构建指定智能体的 MCP server,工具调用按其知识域作用域收敛。"""
    m = FastMCP(f"opc-course-advisor-{role}", instructions=INSTRUCTIONS[role])
    m.settings.transport_security = TransportSecuritySettings(
        allowed_hosts=_ALLOWED_HOSTS, allowed_origins=_ALLOWED_ORIGINS)

    def _scope() -> dict:
        return scope_for_role(role)

    @m.tool()
    def get_welcome() -> dict:
        """获取该智能体的欢迎语与服务范围说明。"""
        return tools.tool_welcome(role)

    @m.tool()
    def ask_knowledge(question: str, product_hint: str = "") -> dict:
        """基于本智能体对接的知识域回答课程问题(大纲/师资/物资/日程/费用说明等),
        返回带引用的答案;范围外资料不可见。"""
        scope = _scope()
        out = apply_scope_ask(scope, {"question": question,
                                      "product_hint": product_hint or None})
        if "error" in out:
            return out
        return tools.tool_ask(out["question"], out.get("product_hint"),
                              out.get("kb_ids"), out.get("domain_ids"))

    @m.tool()
    def recommend_products(city: str = "", date_start: str = "", date_end: str = "",
                           mode: str = "", level: str = "",
                           days_off_continuous: bool | None = None, goal: str = "") -> dict:
        """按约束在本智能体知识域内推荐班型/产品,返回候选与逐条理由;约束不足时返回
        need 列表,应先追问。city/mode=offline|online;日期 YYYY-MM-DD;level=L1/L2/L3。"""
        scope = _scope()
        return tools.tool_recommend(
            city or None, date_start or None, date_end or None, None,
            mode or None, level or None, days_off_continuous, goal or None,
            domain_ids=scope["domain_ids"])

    @m.tool()
    def calculate_fee(product_name: str, payment_date: str,
                      group_count: int = 1, boarding: bool = False,
                      period_name: str = "") -> dict:
        """确定性费用计算:课程费 − 唯一适用优惠 + 自愿食宿,返回逐项拆解。
        payment_date 为 YYYY-MM-DD;group_count 团报人数;boarding 仅部分线下班型有效。"""
        scope = _scope()
        return tools.tool_fee(product_name, payment_date, group_count,
                              boarding, period_name or None,
                              domain_ids=scope["domain_ids"])

    @m.tool()
    def list_products() -> dict:
        """列出本智能体知识域内全部真实班型/产品及其优惠规则。"""
        scope = _scope()
        return tools.tool_list_products(domain_ids=scope["domain_ids"])

    @m.tool()
    def get_enrollment_info(product_name: str = "") -> dict:
        """获取报名流程要点、报名截止、退费规则、改期与前置要求。"""
        scope = _scope()
        return tools.tool_enrollment(product_name or None,
                                     domain_ids=scope["domain_ids"])

    @m.tool()
    def capture_lead(name: str = "", phone: str = "", intent: str = "", note: str = "") -> dict:
        """记录用户报名意向与联系方式,转人工课程顾问跟进(需启用 lead_capture 能力)。
        用户明确表达报名意向、需人工处理时调用;不得虚构余位/报名结果/联系方式。"""
        scope = _scope()
        if not (scope.get("capabilities") or {}).get("lead_capture"):
            return {"error": "本智能体未启用留资转人工能力。"}
        return tools.tool_capture_lead(name, phone, intent, note,
                                       session_id="", agent_role=role)

    return m


# 三个智能体的 MCP 实例
mcp_platform = build_mcp("platform")
mcp_student = build_mcp("student")
mcp_teacher = build_mcp("teacher")


def main() -> None:
    argv = sys.argv[1:]
    transport = "stdio"
    role = "platform"
    for a in argv:
        if a in ("stdio", "http", "streamable-http", "sse"):
            transport = "streamable-http" if a == "http" else a
        elif a in ("platform", "student", "teacher"):
            role = a
    instance = {"platform": mcp_platform, "student": mcp_student, "teacher": mcp_teacher}[role]
    instance.run(transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
