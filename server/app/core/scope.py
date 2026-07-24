"""智能体作用域:知识域对接解析与工具调用范围控制。

Agent 会话循环与 MCP server 共用:每个智能体按 agents.yaml 对接若干知识域,
问答范围即这些知识域——ask_knowledge 按其下知识库(kb_ids)过滤;recommend/fee/
list/enrollment 在对接的知识域内取数,域外数据天然不可见(无需素材级校验)。
"""
from __future__ import annotations

from . import config
from .db import get_db, list_domains, list_kbs


def scope_for_role(role: str) -> dict:
    """解析智能体对接的知识域及其下知识库。兼容旧版 kbs 配置(解析为所属知识域)。"""
    agents = config.agents_config()
    cfg = agents.get(role) or agents.get("platform") or {}
    dom_codes = cfg.get("domains")
    with get_db() as db:
        all_domains = list_domains(db)
        if dom_codes:
            domains = [d for d in all_domains if d["code"] in dom_codes]
        else:
            kb_codes = cfg.get("kbs") or []
            legacy = [k for k in list_kbs(db) if k["code"] in kb_codes]
            dids = {k["domain_id"] for k in legacy if k.get("domain_id")}
            domains = [d for d in all_domains if d["id"] in dids]
        dom_ids = {d["id"] for d in domains}
        kbs = [k for k in list_kbs(db) if k.get("domain_id") in dom_ids]
    return {"domains": domains,
            "domain_ids": sorted(dom_ids),
            "kbs": kbs, "kb_ids": [k["id"] for k in kbs],
            "domain_names": [d["name"] for d in domains],
            "identity": cfg.get("identity"),
            "model": cfg.get("model") or None,
            "capabilities": cfg.get("capabilities") or {}}


def apply_scope_ask(scope: dict, args: dict) -> dict:
    """为 ask_knowledge 注入知识库与知识域范围;未对接任何知识域时返回 {"error": ...}。"""
    args = dict(args)
    args.pop("material", None)   # 已无素材概念,忽略历史参数
    args["kb_ids"] = scope["kb_ids"]
    args["domain_ids"] = scope["domain_ids"]
    if not args["kb_ids"]:
        return {"error": "当前智能体未对接任何知识域,无法作答。"}
    return args
