"""重置 SaaS 演示数据:清空全部租户/用户/会话/订单等种子数据,重建标准演示账号。

保留:平台结构(套餐定义)、官方知识域 domain-a/b/c(/s /t /c 通道)。
新建:
  admin  —— 平台超管(唯一管理用户)
  demo1  —— 旗舰版租户:3 个知识域(学生/教师/平台,摄入 doc/pdf 三份 PDF)+ 3 个智能体
  demo2  —— 标准版租户:1 个知识域 + 默认智能体
  demo3  —— 免费版租户:1 个知识域(入门指南)+ 默认智能体
密码统一 demo1234。

用法(服务停止时执行):
  .venv/Scripts/python scripts/reset_demo_data.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import auth, tenancy                      # noqa: E402
from app.core.db import STARTER_DOC_TEXT, get_db       # noqa: E402
from app.core.ingest.chunk import clear_document_knowledge, ingest_text  # noqa: E402
from app.core.ingest.parse import parse_upload         # noqa: E402

DOC_PDF = ROOT.parent / "doc" / "pdf"
PASSWORD = "demo1234"

# 各智能体的默认欢迎语
AGENT_WELCOMES = {
    "学生课程顾问": "你好!我是本机构的学生课程顾问 🎓 可以解答夏令营班型、营期、费用与上课安排。"
                    "告诉我你的城市和空闲时间,我帮你推荐合适的班型!",
    "教师培训顾问": "你好!我是本机构的教师培训顾问 📚 可以解答 L1—L3 培训体系、班期、前置要求与认证产出。"
                    "告诉我你的时间安排,我帮你匹配集训班或周末研修班。",
    "平台服务顾问": "你好!我是本机构的平台服务顾问 🤝 可以解答平台功能、会员权益与机构合作方式。"
                    "有什么想了解的,尽管问我!",
    "AI 课程顾问": "你好!我是本机构的 AI 课程顾问 🎓 可以解答课程安排、费用与班型推荐。"
                   "请问想了解什么?",
}

# 各智能体的默认系统提示词(角色定位/知识范围/服务方式/沟通风格)
AGENT_PROMPTS = {
    "学生课程顾问": """你是本机构的资深学生课程顾问,面向学生与家长,提供暑期 AI 素养夏令营的课程咨询。

## 你的知识范围
你只解答学生课程知识域内的内容:班型(北京线下/上海线下/线上直播)、营期安排、课程大纲、师资、费用与优惠(早鸟/团报/叠加规则)、食宿与物资准备、报名流程。

## 服务方式
1. 用户咨询课程安排/费用/班型 → 调用工具检索知识域,据实回答并附资料来源。
2. 用户希望推荐班型 → 先了解城市、可用日期与上课偏好,再推荐 1-2 个最匹配的班型并说明理由。
3. 涉及具体费用 → 调用费用计算工具,给出逐项拆解(早鸟/团报按规则取更高优惠)。
4. 用户表达报名意向 → 可记录联系方式转人工顾问跟进,但不承诺余位与报名结果。

## 沟通风格
面向学生与家长亲切、耐心、有条理;不夸大宣传、不编造课程信息,超出知识范围明确告知。""",
    "教师培训顾问": """你是本机构的教师培训顾问,面向初高中教师与学校管理人员,提供 AI 素养培训体系(L1—L3)咨询。

## 你的知识范围
你只解答教师培训知识域内的内容:L1/L2/L3 三级培训体系、集训班/周末研修班、班期与报名截止、前置要求与认证产出、费用与优惠规则。

## 服务方式
1. 用户询问培训等级/班期/费用 → 检索知识域据实回答并附资料来源。
2. 用户希望推荐培训 → 先了解可用日期、能否连续脱岗(集训 vs 周末班),再推荐合适等级与班型。
3. 涉及前置要求 → 明确说明 L2/L3 所需基础与认证路径。
4. 用户表达报名意向 → 可记录联系方式转人工顾问,不承诺名额与结果。

## 沟通风格
面向教师专业、简洁、条理清晰,突出培训体系与认证价值;不编造培训信息。""",
    "平台服务顾问": """你是本机构的平台服务顾问,面向机构、企业与合作伙伴,提供平台与企业服务咨询。

## 你的知识范围
你只解答平台服务知识域内的内容:OPC 平台四大模块、会员服务体系、机构合作方式、大赛与测试安排。

## 服务方式
1. 用户询问平台功能/会员权益/合作方式 → 检索知识域据实回答并附资料来源。
2. 涉及具体报价或合作细则 → 以资料为准,资料缺失时明确告知需与平台运营确认。
3. 用户表达合作/采购意向 → 可记录联系方式转人工顾问跟进。

## 沟通风格
面向机构与企业沉稳、专业、简洁;资料外的平台细节不编造,引导至人工确认。""",
    "AI 课程顾问": """你是本机构的 AI 课程顾问,面向学员与家长提供课程咨询服务。

## 你的知识范围
基于机构知识库回答课程安排、费用、师资、大纲等问题;在资料范围内推荐适合的班型。

## 服务方式
1. 课程事实问题 → 检索知识库据实回答并附资料来源。
2. 班型推荐 → 先了解城市与时间偏好再推荐。
3. 报名/缴费 → 引导联系机构人工确认,不承诺余位与结果。

## 沟通风格
简洁、友好、分点作答;不编造信息,范围外问题如实告知。""",
}


def clear_all(db) -> None:
    """清空租户域数据与全部 SaaS 记录(官方 domain-a/b/c 保留)。"""
    # 1) 租户知识域下的文档知识(块/向量/FTS)、实体、规则、链接
    tenant_docs = [r["id"] for r in db.execute(
        "SELECT d.id FROM documents d JOIN kbs k ON k.id=d.kb_id "
        "JOIN domains dm ON dm.id=k.domain_id WHERE dm.tenant_id IS NOT NULL")]
    for doc_id in tenant_docs:
        clear_document_knowledge(db, doc_id)
        db.execute("DELETE FROM relations WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM entities WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM rules WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.execute("DELETE FROM edges WHERE domain_id IN "
               "(SELECT id FROM domains WHERE tenant_id IS NOT NULL)")
    db.execute("DELETE FROM kbs WHERE domain_id IN "
               "(SELECT id FROM domains WHERE tenant_id IS NOT NULL)")
    db.execute("DELETE FROM domains WHERE tenant_id IS NOT NULL")
    # 2) 会话与消息(全部)、线索、质检、洞察
    db.execute("DELETE FROM messages")
    db.execute("DELETE FROM sessions")
    db.execute("DELETE FROM leads")
    db.execute("DELETE FROM quality_checks")
    db.execute("DELETE FROM insights")
    # 3) SaaS 记录
    db.execute("DELETE FROM tenant_agents")
    db.execute("DELETE FROM usage_monthly")
    db.execute("DELETE FROM payment_orders")
    db.execute("DELETE FROM subscriptions")
    db.execute("DELETE FROM sms_codes")
    db.execute("DELETE FROM users")
    db.execute("DELETE FROM tenants")
    db.execute("DELETE FROM actions_log")


def make_tenant(db, slug: str, name: str, username: str, plan_code: str) -> int:
    cur = db.execute("INSERT INTO tenants(slug, name) VALUES(?,?)", (slug, name))
    tid = cur.lastrowid
    db.execute("INSERT INTO users(tenant_id, username, email, password_hash, role, phone) "
               "VALUES(?,?,?,?, 'admin', '')",
               (tid, username, "", auth.hash_password(PASSWORD)))
    db.execute("INSERT INTO subscriptions(tenant_id, plan_code, status) "
               "VALUES(?,?, 'active')", (tid, plan_code))
    return tid


def make_domain_kb(db, tid: int, code: str, dom_name: str, kb_name: str) -> int:
    db.execute("INSERT INTO domains(code, name, description, tenant_id) VALUES(?,?,?,?)",
               (code, dom_name, "", tid))
    dom_id = db.execute("SELECT id FROM domains WHERE code=?", (code,)).fetchone()["id"]
    db.execute("INSERT INTO kbs(code, name, description, domain_id) VALUES(?,?,?,?)",
               (code.replace("dom-", "kb-"), kb_name, "", dom_id))
    return dom_id


def make_agent(db, tid: int, name: str, domain_ids: list[int], welcome: str = "") -> str:
    agent = tenancy.create_agent(db, tid, name)
    cfg = {"domains": domain_ids}
    if welcome or name in AGENT_WELCOMES:
        cfg["welcome_text"] = welcome or AGENT_WELCOMES.get(name, "")
    if name in AGENT_PROMPTS:
        cfg["prompt_text"] = AGENT_PROMPTS[name]
    import json as _json
    db.execute("UPDATE tenant_agents SET config_json=? WHERE id=?",
               (_json.dumps(cfg, ensure_ascii=False), agent["id"]))
    return agent["slug"]


# 本体抽取按章调 LLM,三份 PDF 合计数分钟。Docker 首启为压缩评审等待时间
# 默认跳过(RAG 问答只依赖知识块,不依赖本体);设 DEMO_SKIP_EXTRACT=0 可强制完整抽取。
SKIP_EXTRACT = os.environ.get("DEMO_SKIP_EXTRACT", "0") == "1"


def ingest_pdf(db, kb_id: int, pdf_path: Path, title: str) -> None:
    text = parse_upload(pdf_path.name, pdf_path.read_bytes())
    stats = ingest_text(db, kb_id, pdf_path.name, title, text,
                        do_extract=not SKIP_EXTRACT)
    ex = stats.get("extract") or {}
    print(f"    摄入 {pdf_path.name}: 块 {stats.get('chunks')} · "
          f"实体 {ex.get('entities')} · 规则 {ex.get('rules')}"
          + ("  (已跳过本体抽取)" if SKIP_EXTRACT else ""))


def main() -> int:
    with get_db() as db:
        print("1/5 清空种子数据…")
        clear_all(db)

        print("2/5 创建平台超管 admin …")
        db.execute("INSERT INTO users(username, email, password_hash, role, phone) "
                   "VALUES('admin','',?, 'superadmin','')", (auth.hash_password(PASSWORD),))

        print("3/5 创建 demo1(旗舰版):3 知识域 + 3 PDF + 3 智能体…")
        t1 = make_tenant(db, "demo1", "演示机构一(旗舰版)", "demo1", "flagship")
        d1a = make_domain_kb(db, t1, "dom-d1stu", "学生课程知识域", "学生课程知识库")
        d1b = make_domain_kb(db, t1, "dom-d1tea", "教师培训知识域", "教师培训知识库")
        d1c = make_domain_kb(db, t1, "dom-d1plt", "平台服务知识域", "平台服务知识库")
        kb1a = db.execute("SELECT id FROM kbs WHERE code='kb-d1stu'").fetchone()["id"]
        kb1b = db.execute("SELECT id FROM kbs WHERE code='kb-d1tea'").fetchone()["id"]
        kb1c = db.execute("SELECT id FROM kbs WHERE code='kb-d1plt'").fetchone()["id"]
        ingest_pdf(db, kb1a, DOC_PDF / "学生个人课程资料.pdf", "学生个人课程资料")
        ingest_pdf(db, kb1b, DOC_PDF / "教师个人培训资料.pdf", "教师个人培训资料")
        ingest_pdf(db, kb1c, DOC_PDF / "平台与企业服务资料.pdf", "平台与企业服务资料")
        s1 = make_agent(db, t1, "学生课程顾问", [d1a],
                        "你好!我是学生课程顾问,可以解答夏令营课程安排、费用与班型推荐。")
        s2 = make_agent(db, t1, "教师培训顾问", [d1b],
                        "你好!我是教师培训顾问,可以解答 L1—L3 培训体系、班期与报名规则。")
        s3 = make_agent(db, t1, "平台服务顾问", [d1c],
                        "你好!我是平台服务顾问,可以解答平台与企业合作、会员服务体系。")
        print(f"    智能体链接: /b/{s1}  /b/{s2}  /b/{s3}")

        print("4/5 创建 demo2(标准版)…")
        t2 = make_tenant(db, "demo2", "演示机构二(标准版)", "demo2", "standard")
        d2 = make_domain_kb(db, t2, "dom-d2main", "课程知识域", "课程知识库")
        kb2 = db.execute("SELECT id FROM kbs WHERE code='kb-d2main'").fetchone()["id"]
        ingest_text(db, kb2, "平台使用指南.txt", "平台使用指南",
                    STARTER_DOC_TEXT, do_extract=False)
        make_agent(db, t2, "AI 课程顾问", [])

        print("5/5 创建 demo3(免费版)…")
        t3 = make_tenant(db, "demo3", "演示机构三(免费版)", "demo3", "free")
        d3 = make_domain_kb(db, t3, "dom-d3main", "课程知识域", "课程知识库")
        kb3 = db.execute("SELECT id FROM kbs WHERE code='kb-d3main'").fetchone()["id"]
        ingest_text(db, kb3, "平台使用指南.txt", "平台使用指南",
                    STARTER_DOC_TEXT, do_extract=False)
        make_agent(db, t3, "AI 课程顾问", [])

    print("\n完成。账号(密码均 demo1234):")
    print("  admin —— 平台超管 /portal")
    print("  demo1 —— 旗舰版(3 知识域 + 3 智能体)")
    print("  demo2 —— 标准版(限 3 智能体,能力开关锁定)")
    print("  demo3 —— 免费版(限 1 智能体,知识域对接/能力开关锁定)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
