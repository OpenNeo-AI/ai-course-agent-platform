"""多租户:注册开通、租户作用域、用量配额、内容脱敏。

- register_tenant:事务内建 租户+管理员+知识域+知识库+免费订阅,并摄入入门指南,
  保证免费版 Bot 开通即可对话。
- scope_for_tenant:返回与 scope.scope_for_role 同构的 dict,loop.py 无感切换。
- 配额:usage_monthly 按自然月(北京时间)计数;pro 套餐 chat_limit_month=-1 不限。
- 官方演示三通道(会话 tenant_id=NULL)不受配额与租户作用域影响。
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from . import auth
from .db import STARTER_DOC_TEXT, STARTER_DOC_TITLE, get_db
from .ingest.chunk import ingest_text

_CST = timezone(timedelta(hours=8))


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(_CST)).strftime("%Y-%m")


# ---------- 注册开通 ----------

def _valid_username(u: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{3,24}", u or ""))


def register_tenant(org_name: str, username: str, password: str, email: str = "",
                    phone: str = "") -> dict:
    """开通新租户;失败抛 ValueError(前端转 400)。
    手机验证码注册时 username/password 可缺省,自动生成(登录走短信验证码)。"""
    org_name = (org_name or "").strip()
    username = (username or "").strip().lower()
    if phone and not username:
        username = f"m{phone[-4:]}{secrets.token_hex(2)}"
    if phone and not password:
        password = secrets.token_urlsafe(12)
    if not org_name or len(org_name) > 40:
        raise ValueError("机构名称需在 1-40 字之间")
    if not _valid_username(username):
        raise ValueError("用户名需为 3-24 位字母/数字/下划线/中划线")
    if not password or len(password) < 6:
        raise ValueError("密码至少 6 位")

    slug = "org-" + secrets.token_hex(2)
    suffix = secrets.token_hex(3)
    dom_code, kb_code = f"dom-t{suffix}", f"kb-t{suffix}"
    with get_db() as db:
        exists = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if exists:
            raise ValueError("用户名已被占用")
        if phone and db.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
            raise ValueError("该手机号已注册")
        cur = db.execute("INSERT INTO tenants(slug, name) VALUES(?,?)", (slug, org_name))
        tid = cur.lastrowid
        db.execute("INSERT INTO users(tenant_id, username, email, password_hash, role, phone) "
                   "VALUES(?,?,?,?,?,?)",
                   (tid, username, email or "", auth.hash_password(password), "admin",
                    phone or ""))
        # 注册即开通免费版(仅智能体设置可用);标准版/旗舰版付费升级
        db.execute("INSERT INTO subscriptions(tenant_id, plan_code, status) "
                   "VALUES(?,?, 'active')", (tid, "free"))
        db.execute("INSERT INTO domains(code, name, description, tenant_id) VALUES(?,?,?,?)",
                   (dom_code, f"{org_name}·课程知识域", "租户自有课程知识", tid))
        dom_id = db.execute("SELECT id FROM domains WHERE code=?", (dom_code,)).fetchone()["id"]
        db.execute("INSERT INTO kbs(code, name, description, domain_id) VALUES(?,?,?,?)",
                   (kb_code, f"{org_name}·课程知识库", "租户自有知识库", dom_id))
        kb_id = db.execute("SELECT id FROM kbs WHERE code=?", (kb_code,)).fetchone()["id"]
        # 入门指南:开通后即可对话(内容为平台自身说明,不涉及课程事实)。
        # do_extract=False:跳过 LLM 抽取,避免注册事务长时间持锁。
        try:
            ingest_text(db, kb_id, "平台使用指南.txt", STARTER_DOC_TITLE,
                        STARTER_DOC_TEXT, do_extract=False)
        except Exception as e:  # noqa: BLE001
            db.execute("UPDATE kbs SET description=? WHERE id=?",
                       (f"租户自有知识库(入门资料摄入失败:{type(e).__name__})", kb_id))
    return {"tenant_id": tid, "slug": slug, "name": org_name, "username": username}


def get_tenant_by_slug(slug: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM tenants WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None


# ---------- 租户作用域(与 scope_for_role 同构) ----------

def bot_config_of(db, tenant_id: int) -> dict:
    row = db.execute("SELECT bot_config_json FROM tenants WHERE id=?",
                     (tenant_id,)).fetchone()
    try:
        return json.loads((row["bot_config_json"] if row else "") or "{}")
    except (ValueError, TypeError):
        return {}


def tenant_welcome(db, tenant_id: int) -> str | None:
    """租户自定义欢迎语(智能体设置);未配置返回 None 走全局模板。"""
    return (bot_config_of(db, tenant_id).get("welcome_text") or "").strip() or None


def tenant_prompt(db, tenant_id: int) -> str | None:
    """租户自定义系统提示词(智能体设置);未配置返回 None 用平台 tenant.md。"""
    return (bot_config_of(db, tenant_id).get("prompt_text") or "").strip() or None


def scope_for_tenant(tenant_id: int) -> dict:
    """租户作用域(兼容入口):取该租户默认智能体的作用域。"""
    with get_db() as db:
        agent = db.execute("SELECT * FROM tenant_agents WHERE tenant_id=? ORDER BY id",
                           (tenant_id,)).fetchone()
    if not agent:
        return {"domains": [], "domain_ids": [], "kbs": [], "kb_ids": [],
                "domain_names": [], "identity": "tenant", "model": None,
                "capabilities": {"tenant_bot": True}}
    return scope_for_agent(agent)


# ---------- 租户智能体(多智能体:独立配置 + 独立前台链接) ----------

def agent_config_of(agent) -> dict:
    try:
        return json.loads(agent["config_json"] or "{}")
    except (ValueError, TypeError):
        return {}


def list_agents(db, tenant_id: int) -> list[dict]:
    rows = db.execute("SELECT * FROM tenant_agents WHERE tenant_id=? ORDER BY id",
                      (tenant_id,)).fetchall()
    out = []
    for r in rows:
        cfg = agent_config_of(r)
        out.append({"id": r["id"], "slug": r["slug"], "name": r["name"],
                    "created_at": r["created_at"],
                    "link": f"/b/{r['slug']}",
                    "config": {"welcome_text": cfg.get("welcome_text", ""),
                               "prompt_text": cfg.get("prompt_text", ""),
                               "lead_capture": cfg.get("lead_capture", True),
                               "quality_check": cfg.get("quality_check", True),
                               "domains": cfg.get("domains") or [],
                               "model": cfg.get("model") or ""},
                    "domain_count": len(cfg.get("domains") or [])})
    return out


def get_agent(db, agent_id: int):
    return db.execute("SELECT * FROM tenant_agents WHERE id=?", (agent_id,)).fetchone()


def get_agent_by_slug(db, slug: str):
    return db.execute("SELECT * FROM tenant_agents WHERE slug=?", (slug,)).fetchone()


def create_agent(db, tenant_id: int, name: str) -> dict:
    """新建智能体;套餐数量限额在调用方(API 层)校验。"""
    slug = "a-" + secrets.token_hex(3)
    while db.execute("SELECT 1 FROM tenant_agents WHERE slug=?", (slug,)).fetchone():
        slug = "a-" + secrets.token_hex(3)
    cur = db.execute("INSERT INTO tenant_agents(tenant_id, slug, name, config_json) "
                     "VALUES(?,?,?,?)", (tenant_id, slug, (name or "").strip(), "{}"))
    return dict(db.execute("SELECT * FROM tenant_agents WHERE id=?",
                           (cur.lastrowid,)).fetchone())


def delete_agent(db, tenant_id: int, agent_id: int) -> None:
    cnt = db.execute("SELECT COUNT(*) FROM tenant_agents WHERE tenant_id=?",
                     (tenant_id,)).fetchone()[0]
    if cnt <= 1:
        raise ValueError("至少保留一个智能体")
    row = db.execute("SELECT id FROM tenant_agents WHERE id=? AND tenant_id=?",
                     (agent_id, tenant_id)).fetchone()
    if not row:
        raise ValueError("智能体不存在")
    # 历史会话解除绑定(后续对话回退到该租户默认智能体)
    db.execute("UPDATE sessions SET agent_id=NULL WHERE agent_id=?", (agent_id,))
    db.execute("DELETE FROM tenant_agents WHERE id=?", (agent_id,))


def scope_for_agent(agent) -> dict:
    """智能体作用域:知识域按配置挂载列表过滤(空=挂载租户全部知识域)。"""
    from .db import list_domains, list_kbs
    cfg = agent_config_of(agent)
    with get_db() as db:
        domains = [d for d in list_domains(db) if d.get("tenant_id") == agent["tenant_id"]]
        bound = cfg.get("domains") or []
        if bound:
            bound_ids = set(bound)
            domains = [d for d in domains if d["id"] in bound_ids]
        dom_ids = {d["id"] for d in domains}
        kbs = [k for k in list_kbs(db) if k.get("domain_id") in dom_ids]
    return {"domains": domains,
            "domain_ids": sorted(dom_ids),
            "kbs": kbs, "kb_ids": [k["id"] for k in kbs],
            "domain_names": [d["name"] for d in domains],
            "identity": "tenant",
            "model": cfg.get("model") or None,
            "capabilities": {"tenant_bot": True,
                             "lead_capture": bool(cfg.get("lead_capture", True)),
                             "quality_check": bool(cfg.get("quality_check", True))}}


def agent_welcome(agent) -> str | None:
    return (agent_config_of(agent).get("welcome_text") or "").strip() or None


def agent_prompt(agent) -> str | None:
    return (agent_config_of(agent).get("prompt_text") or "").strip() or None


# ---------- 套餐与配额 ----------

def subscription_of(db: sqlite3.Connection, tenant_id: int) -> dict:
    row = db.execute(
        "SELECT s.plan_code, s.status, p.name AS plan_name, p.chat_limit_month, "
        "p.features_json "
        "FROM subscriptions s JOIN plans p ON p.code=s.plan_code "
        "WHERE s.tenant_id=?", (tenant_id,)).fetchone()
    if not row:
        return {"plan_code": "standard", "status": "unpaid", "plan_name": "标准版",
                "chat_limit_month": -1, "features_json": "{}"}
    return dict(row)


def is_active(db: sqlite3.Connection, tenant_id: int) -> bool:
    """订阅是否生效(已支付开通)。"""
    return subscription_of(db, tenant_id).get("status") == "active"


def usage_of(db: sqlite3.Connection, tenant_id: int, ym: str | None = None) -> int:
    ym = ym or month_key()
    row = db.execute("SELECT chat_count FROM usage_monthly WHERE tenant_id=? AND year_month=?",
                     (tenant_id, ym)).fetchone()
    return row["chat_count"] if row else 0


def quota_state(db: sqlite3.Connection, tenant_id: int) -> dict:
    sub = subscription_of(db, tenant_id)
    used = usage_of(db, tenant_id)
    limit = sub["chat_limit_month"]
    unlimited = limit is not None and limit < 0
    return {"plan_code": sub["plan_code"], "plan_name": sub["plan_name"],
            "limit": -1 if unlimited else limit, "unlimited": unlimited,
            "used": used,
            "remaining": -1 if unlimited else max(0, limit - used)}


def quota_check(db: sqlite3.Connection, tenant_id: int) -> bool:
    q = quota_state(db, tenant_id)
    return q["unlimited"] or q["used"] < q["limit"]


def quota_inc(db: sqlite3.Connection, tenant_id: int) -> None:
    ym = month_key()
    db.execute("INSERT INTO usage_monthly(tenant_id, year_month, chat_count) VALUES(?,?,1) "
               "ON CONFLICT(tenant_id, year_month) DO UPDATE SET chat_count=chat_count+1",
               (tenant_id, ym))


# ---------- 脱敏(对话记录展示) ----------

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_IDCARD_RE = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")


def mask_text(text: str | None) -> str:
    """手机号/邮箱/身份证号打码;None 原样返回。"""
    if not text:
        return text
    text = _IDCARD_RE.sub(r"\1********\2", text)
    text = _PHONE_RE.sub(r"\1****\2", text)
    text = _EMAIL_RE.sub(r"\1***\2", text)
    return text
