"""SaaS 端点:认证(注册/登录/JWT)、套餐订阅、租户管理。

路由分组:
  /api/auth/*      注册、登录、当前用户
  /api/plans       套餐列表(公开,套餐展示页)
  /api/billing/*   订单与支付演示(P2 补充)
  /api/tenant/*    租户 Admin:资料/对话记录/用量(P3 补充)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..core import auth, config, tenancy
from ..core.db import get_db

router = APIRouter(tags=["saas"])


# ---------- JWT 鉴权依赖 ----------

def bearer_token(request: Request) -> str:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def jwt_user(request: Request) -> dict:
    """解析 JWT 并返回用户记录;无效/不存在均 401。"""
    payload = auth.decode_token(bearer_token(request))
    if not payload:
        raise HTTPException(status_code=401, detail="未授权:登录态缺失或已过期")
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id=?", (payload.get("sub"),)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="未授权:用户不存在")
    return dict(row)


def require_admin(request: Request) -> dict:
    user = jwt_user(request)
    if user["role"] not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ---------- 认证 ----------

@router.post("/api/auth/register")
async def register(request: Request):
    """租户自助注册:机构名+管理员账号+密码 → 自动开通(知识域/知识库/免费订阅)。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    try:
        t = tenancy.register_tenant(body.get("org_name", ""), body.get("username", ""),
                                    body.get("password", ""), body.get("email", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    with get_db() as db:
        user = dict(db.execute("SELECT * FROM users WHERE username=?",
                               (t["username"],)).fetchone())
    return {"ok": True, "token": auth.issue_token(user),
            "user": {"username": user["username"], "role": user["role"],
                     "tenant_id": t["tenant_id"]},
            "tenant": {"id": t["tenant_id"], "slug": t["slug"], "name": t["name"]}}


# ---------- 手机验证码(参照 OpenNeo:阿里云短信 + verification_codes 移植) ----------

@router.post("/api/auth/sms/send")
async def sms_send(request: Request):
    """发送验证码:60 秒/条、每小时 ≤5 条;未配置短信密钥时为演示模式
    (验证码随响应返回并明确标注 demo,保证评审可复现)。"""
    from ..core import sms
    try:
        body = await request.json()
    except Exception:
        body = {}
    r = sms.send_code(((body or {}).get("phone") or "").strip())
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "发送失败"))
    return r


@router.post("/api/auth/sms/login")
async def sms_login(request: Request):
    """手机号 + 验证码登录(用户须已注册;未注册引导注册开通)。"""
    from ..core import sms
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    phone = (body.get("phone") or "").strip()
    if not sms.verify_code(phone, body.get("code") or ""):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
        if not user:
            raise HTTPException(status_code=404,
                                detail="该手机号未注册,请先注册开通机构")
        user = dict(user)
        tenant = None
        if user["tenant_id"]:
            t = db.execute("SELECT * FROM tenants WHERE id=?",
                           (user["tenant_id"],)).fetchone()
            tenant = dict(t) if t else None
    return {"ok": True, "token": auth.issue_token(user),
            "user": {"username": user["username"], "role": user["role"],
                     "tenant_id": user["tenant_id"]},
            "tenant": tenant}


@router.post("/api/auth/sms/register")
async def sms_register(request: Request):
    """手机验证码注册开通:机构名 + 账户 + 密码 + 手机号 + 验证码
    → 租户 + 管理员 + 免费版订阅。账户用于密码登录;手机号用于验证码登录。
    (账户/密码缺省时自动生成,兼容纯手机号注册调用。)"""
    from ..core import sms
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    phone = (body.get("phone") or "").strip()
    if not sms.verify_code(phone, body.get("code") or ""):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    with get_db() as db:
        if db.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
            raise HTTPException(status_code=400, detail="该手机号已注册,请直接登录")
    try:
        t = tenancy.register_tenant(body.get("org_name", ""),
                                    (body.get("username") or "").strip().lower(),
                                    body.get("password", ""), body.get("email", ""),
                                    phone=phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    with get_db() as db:
        user = dict(db.execute("SELECT * FROM users WHERE username=?",
                               (t["username"],)).fetchone())
    return {"ok": True, "token": auth.issue_token(user),
            "user": {"username": user["username"], "role": user["role"],
                     "tenant_id": t["tenant_id"]},
            "tenant": {"id": t["tenant_id"], "slug": t["slug"], "name": t["name"]}}


@router.post("/api/auth/login")
async def login(request: Request):
    """密码登录:账户名或注册手机号均可作为登录名。"""
    import re as _re
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    username = (body.get("username") or "").strip().lower()
    password = body.get("password") or ""
    with get_db() as db:
        if _re.fullmatch(r"1[3-9]\d{9}", username):
            row = db.execute("SELECT * FROM users WHERE phone=?", (username,)).fetchone()
        else:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not row or not auth.verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="账户或密码错误")
        user = dict(row)
        tenant = None
        if user["tenant_id"]:
            t = db.execute("SELECT * FROM tenants WHERE id=?",
                           (user["tenant_id"],)).fetchone()
            tenant = dict(t) if t else None
    return {"ok": True, "token": auth.issue_token(user),
            "user": {"username": user["username"], "role": user["role"],
                     "tenant_id": user["tenant_id"]},
            "tenant": tenant}


@router.get("/api/auth/me")
def me(request: Request):
    """当前登录用户 + 租户 + 订阅 + 当月配额(Portal/Admin 分叉依据)。
    兼容静态 portal token(视为平台超管,支撑存量 Portal 登录)。"""
    from ..core import config as core_config
    tok = bearer_token(request)
    if tok and tok == core_config.portal_token():
        return {"user": {"username": "portal", "role": "superadmin", "tenant_id": None},
                "tenant": None, "subscription": None, "quota": None}
    user = jwt_user(request)
    out = {"user": {"username": user["username"], "role": user["role"],
                    "tenant_id": user["tenant_id"]},
           "tenant": None, "subscription": None, "quota": None}
    if not user["tenant_id"]:
        return out
    with get_db() as db:
        t = db.execute("SELECT * FROM tenants WHERE id=?", (user["tenant_id"],)).fetchone()
        out["tenant"] = dict(t) if t else None
        sub = tenancy.subscription_of(db, user["tenant_id"])
        out["subscription"] = {**sub,
                               "features": json.loads(sub.get("features_json") or "{}")}
        out["quota"] = tenancy.quota_state(db, user["tenant_id"])
    return out


# ---------- 套餐(公开) ----------

@router.get("/api/plans")
def plans():
    with get_db() as db:
        rows = db.execute("SELECT * FROM plans ORDER BY price_monthly").fetchall()
    out = []
    for r in rows:
        out.append({"code": r["code"], "name": r["name"],
                    "price_monthly": r["price_monthly"],
                    "chat_limit_month": r["chat_limit_month"],
                    "features": json.loads(r["features_json"] or "{}")})
    return {"plans": out}


# ---------- 订阅 / 支付演示 / 用量 ----------

def _tenant_of(user: dict) -> int:
    if not user["tenant_id"]:
        raise HTTPException(status_code=400, detail="平台账户无租户订阅")
    return user["tenant_id"]


@router.get("/api/billing/subscription")
def subscription(request: Request):
    user = jwt_user(request)
    tid = _tenant_of(user)
    with get_db() as db:
        sub = tenancy.subscription_of(db, tid)
        return {"subscription": {**sub,
                                 "features": json.loads(sub.get("features_json") or "{}")},
                "quota": tenancy.quota_state(db, tid)}


@router.get("/api/billing/channels")
def billing_channels():
    """支付渠道可用性(mock 恒可用;微信/支付宝按 .env 配置)。"""
    from ..core import payments
    return {"channels": payments.channels_status()}


@router.post("/api/billing/orders")
async def create_order(request: Request):
    """选套餐下单:mock=演示;wechat=微信扫码(pay_info.code_url);
    alipay=电脑网站支付(pay_info.pay_url)。"""
    from ..core import payments
    user = jwt_user(request)
    tid = _tenant_of(user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    try:
        order = payments.create_order(tid, body.get("plan_code", "standard"),
                                      body.get("channel", "mock"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "order": order}


@router.post("/api/billing/orders/{order_id}/confirm")
def confirm_order(order_id: int, request: Request):
    """模拟支付确认(仅 mock 渠道);真实渠道走 查询/回调 确认。"""
    from ..core import payments
    user = jwt_user(request)
    tid = _tenant_of(user)
    with get_db() as db:
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
    if not order or order["tenant_id"] != tid:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["channel"] != "mock":
        raise HTTPException(status_code=400,
                            detail="该订单为真实渠道,请通过支付状态查询确认")
    try:
        return {"ok": True, **payments.pay_success(order_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/billing/orders/{order_id}/status")
def order_status(order_id: int, request: Request):
    """轮询支付结果:主动向渠道查单;成功即升级订阅。"""
    from ..core import payments
    user = jwt_user(request)
    tid = _tenant_of(user)
    with get_db() as db:
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
    if not order or order["tenant_id"] != tid:
        raise HTTPException(status_code=404, detail="订单不存在")
    try:
        r = payments.query_order(order_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **r}


# ---------- 支付回调(公开端点,渠道服务端通知) ----------

@router.post("/api/billing/callback/wechat")
async def wechat_callback(request: Request):
    """微信 Native 支付回调:XML + MD5 验签(补齐 OpenNeo 缺失的服务端确认)。"""
    from fastapi.responses import Response
    from ..core import payments
    body = await request.body()
    try:
        info = payments.CHANNELS["wechat"].parse_callback(
            body, request.headers.get("content-type", ""))
        r = payments.pay_by_out_trade_no(info["out_trade_no"], info.get("trade_no", ""))
        if r:
            return Response(
                "<xml><return_code><![CDATA[SUCCESS]]></return_code>"
                "<return_msg><![CDATA[OK]]></return_msg></xml>",
                media_type="application/xml")
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("微信回调处理失败: %s", e)
    return Response(
        "<xml><return_code><![CDATA[FAIL]]></return_code>"
        "<return_msg><![CDATA[FAIL]]></return_msg></xml>",
        media_type="application/xml")


@router.post("/api/billing/callback/alipay")
async def alipay_callback(request: Request):
    """支付宝异步通知:表单 + RSA2 验签,成功返回纯文本 success。"""
    from fastapi.responses import PlainTextResponse
    from ..core import payments
    body = await request.body()
    try:
        info = payments.CHANNELS["alipay"].parse_callback(
            body, request.headers.get("content-type", ""))
        if payments.pay_by_out_trade_no(info["out_trade_no"], info.get("trade_no", "")):
            return PlainTextResponse("success")
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("支付宝回调处理失败: %s", e)
    return PlainTextResponse("fail")


@router.get("/api/billing/orders")
def list_orders(request: Request):
    user = jwt_user(request)
    tid = _tenant_of(user)
    with get_db() as db:
        rows = db.execute("SELECT * FROM payment_orders WHERE tenant_id=? ORDER BY id DESC",
                          (tid,)).fetchall()
    return {"orders": [dict(r) for r in rows]}


@router.get("/api/usage")
def usage(request: Request):
    """当月用量与近 6 个月趋势(租户 Admin 用量页)。"""
    user = jwt_user(request)
    tid = _tenant_of(user)
    from datetime import datetime, timedelta, timezone
    cst = timezone(timedelta(hours=8))
    now = datetime.now(cst)
    months = [(now - timedelta(days=30 * i)).strftime("%Y-%m") for i in range(6)][::-1]
    with get_db() as db:
        quota = tenancy.quota_state(db, tid)
        rows = db.execute("SELECT year_month, chat_count FROM usage_monthly "
                          "WHERE tenant_id=? AND year_month IN ({})".format(
                              ",".join("?" * len(months))),
                          [tid, *months]).fetchall()
    by_month = {r["year_month"]: r["chat_count"] for r in rows}
    return {"quota": quota,
            "trend": [{"month": m, "count": by_month.get(m, 0)} for m in months]}


# ---------- Agent Skill 自描述 ----------

@router.get("/api/skills")
def skills():
    """Agent Skill 清单:名称/描述/参数 JSON Schema/返回值定义(测试单查验口径)。"""
    from ..core import tools as core_tools
    return {"skills": core_tools.SKILLS_META,
            "degradation": "参数缺失→返回 need 列表由 Agent 追问;班型不存在→返回 available 列表;"
                           "模型服务异常→固定降级文案;工具不可用时 Agent 基于上下文直答并声明不确定。"}


# ---------- 租户 Admin ----------

def _tenant_ctx(request: Request) -> tuple[dict, dict]:
    """租户管理员上下文:(tenant, features);非租户管理员 403。"""
    user = require_admin(request)
    tid = _tenant_of(user)
    with get_db() as db:
        t = db.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
        if not t:
            raise HTTPException(status_code=404, detail="租户不存在")
        features = json.loads(tenancy.subscription_of(db, tid).get("features_json") or "{}")
    return dict(t), features


def _tenant_kb_ids(db, tenant_id: int) -> list[int]:
    rows = db.execute(
        "SELECT k.id FROM kbs k JOIN domains d ON d.id=k.domain_id "
        "WHERE d.tenant_id=?", (tenant_id,)).fetchall()
    return [r["id"] for r in rows]


# ---------- 机构信息维护(机构名称 + 统一服务宗旨) ----------

@router.get("/api/tenant/institution")
def get_institution(request: Request):
    t, _ = _tenant_ctx(request)
    with get_db() as db:
        purpose = tenancy.tenant_service_purpose(db, t["id"])
    return {"name": t["name"], "service_purpose": purpose}


@router.put("/api/tenant/institution")
async def put_institution(request: Request):
    """维护机构名称与统一服务宗旨(注入该机构所有智能体的系统提示词)。"""
    t, _ = _tenant_ctx(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    fields, args = [], []
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name or len(name) > 40:
            raise HTTPException(status_code=400, detail="机构名称需在 1-40 字之间")
        fields.append("name=?")
        args.append(name)
    if "service_purpose" in body:
        purpose = (body.get("service_purpose") or "").strip()
        if len(purpose) > 500:
            raise HTTPException(status_code=400, detail="服务宗旨不超过 500 字")
        fields.append("service_purpose=?")
        args.append(purpose)
    if not fields:
        raise HTTPException(status_code=400, detail="无可更新字段")
    args.append(t["id"])
    with get_db() as db:
        db.execute(f"UPDATE tenants SET {', '.join(fields)} WHERE id=?", args)
    return {"ok": True, "name": body.get("name", t["name"]),
            "service_purpose": (body.get("service_purpose", "") or "").strip()}


# ---------- 租户智能体管理(多智能体:独立配置 + 独立前台链接 /b/<slug>) ----------
# 套餐门禁:知识域对接=标准版起(domains);能力开关=旗舰版(agent_caps);
# 数量限额:免费 1 / 标准 3 / 旗舰不限(plans.agent_limit)。

def _agent_owned(request: Request, agent_id: int):
    """校验智能体归属本租户;返回 (tenant, features, agent_row)。"""
    t, features = _tenant_ctx(request)
    with get_db() as db:
        agent = tenancy.get_agent(db, agent_id)
    if not agent or agent["tenant_id"] != t["id"]:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return t, features, agent


@router.get("/api/tenant/agents")
def list_tenant_agents(request: Request):
    t, features = _tenant_ctx(request)
    with get_db() as db:
        agents = tenancy.list_agents(db, t["id"])
        sub = tenancy.subscription_of(db, t["id"])
        plan = db.execute("SELECT agent_limit FROM plans WHERE code=?",
                          (sub["plan_code"],)).fetchone()
    return {"agents": agents,
            "agent_limit": plan["agent_limit"] if plan else 1,
            "features": features}


@router.post("/api/tenant/agents")
async def create_tenant_agent(request: Request):
    t, _ = _tenant_ctx(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = ((body or {}).get("name") or "").strip()
    if not name or len(name) > 20:
        raise HTTPException(status_code=400, detail="智能体名称需在 1-20 字之间")
    with get_db() as db:
        sub = tenancy.subscription_of(db, t["id"])
        plan = db.execute("SELECT agent_limit FROM plans WHERE code=?",
                          (sub["plan_code"],)).fetchone()
        limit = plan["agent_limit"] if plan else 1
        cnt = db.execute("SELECT COUNT(*) FROM tenant_agents WHERE tenant_id=?",
                         (t["id"],)).fetchone()[0]
        if limit >= 0 and cnt >= limit:
            raise HTTPException(status_code=402,
                                detail=f"当前套餐最多 {limit} 个智能体,请升级套餐后新建")
        agent = tenancy.create_agent(db, t["id"], name)
    return {"ok": True, "agent": {"id": agent["id"], "slug": agent["slug"],
                                  "name": agent["name"],
                                  "link": f"/b/{agent['slug']}"}}


@router.delete("/api/tenant/agents/{agent_id}")
def delete_tenant_agent(agent_id: int, request: Request):
    t, _, _ = _agent_owned(request, agent_id)
    with get_db() as db:
        try:
            tenancy.delete_agent(db, t["id"], agent_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/api/tenant/agents/{agent_id}/config")
def get_agent_config(agent_id: int, request: Request):
    t, features, agent = _agent_owned(request, agent_id)
    llm_cfg = config.llm_config()
    models = llm_cfg.get("chat_models") or []
    if llm_cfg.get("chat_model"):
        models = [llm_cfg["chat_model"], *[m for m in models if m != llm_cfg["chat_model"]]]
    cfg = tenancy.agent_config_of(agent)
    return {"config": {"welcome_text": cfg.get("welcome_text", ""),
                       "prompt_text": cfg.get("prompt_text", ""),
                       "lead_capture": cfg.get("lead_capture", True),
                       "quality_check": cfg.get("quality_check", True),
                       "domains": cfg.get("domains") or [],
                       "model": cfg.get("model") or ""},
            "model_options": models,
            "default_model": llm_cfg.get("chat_model") or "",
            "features": features,
            "link": f"/b/{agent['slug']}",
            "agent": {"id": agent["id"], "slug": agent["slug"], "name": agent["name"]}}


@router.put("/api/tenant/agents/{agent_id}/config")
async def put_agent_config(agent_id: int, request: Request):
    """更新智能体配置;热生效(新会话即采用)。
    门禁:domains=标准版+;lead_capture/quality_check=旗舰版;其余字段各套餐可用。"""
    from .portal import _tenant_domain_ids
    t, features, agent = _agent_owned(request, agent_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    with get_db() as db:
        cfg = tenancy.agent_config_of(agent)
        if "welcome_text" in body:
            wt = (body.get("welcome_text") or "").strip()
            if len(wt) > 800:
                raise HTTPException(status_code=400, detail="欢迎语不超过 800 字")
            cfg["welcome_text"] = wt
        if "prompt_text" in body:
            pt = (body.get("prompt_text") or "").strip()
            if len(pt) > 4000:
                raise HTTPException(status_code=400, detail="系统提示词不超过 4000 字")
            cfg["prompt_text"] = pt
        if "lead_capture" in body or "quality_check" in body:
            if not features.get("agent_caps"):
                raise HTTPException(status_code=402,
                                    detail="能力开关为旗舰版功能,请先升级套餐")
            if "lead_capture" in body:
                cfg["lead_capture"] = bool(body["lead_capture"])
            if "quality_check" in body:
                cfg["quality_check"] = bool(body["quality_check"])
        if "domains" in body:
            if not features.get("domains"):
                raise HTTPException(status_code=402,
                                    detail="知识域对接为标准版功能,请先升级套餐")
            own = set(_tenant_domain_ids(db, t["id"]))
            try:
                sel = [int(d) for d in (body.get("domains") or [])]
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="domains 需为知识域 id 列表")
            if not set(sel) <= own:
                raise HTTPException(status_code=400, detail="包含不属于本租户的知识域")
            cfg["domains"] = sel
        if "model" in body:
            cfg["model"] = (body.get("model") or "").strip() or None
        db.execute("UPDATE tenant_agents SET config_json=? WHERE id=?",
                   (json.dumps(cfg, ensure_ascii=False), agent["id"]))
    return {"ok": True, "config": cfg}


@router.get("/api/tenant/info")
def tenant_info(request: Request):
    """租户概览:机构信息 + 订阅 + 配额 + Bot 入口 slug。"""
    t, features = _tenant_ctx(request)
    user = jwt_user(request)
    with get_db() as db:
        sub = tenancy.subscription_of(db, t["id"])
        quota = tenancy.quota_state(db, t["id"])
        kb_ids = _tenant_kb_ids(db, t["id"])
        docs = 0
        if kb_ids:
            ph = ",".join("?" * len(kb_ids))
            docs = db.execute(
                f"SELECT COUNT(*) FROM documents d WHERE d.kb_id IN ({ph})",
                kb_ids).fetchone()[0]
    return {"tenant": t,
            "subscription": {**sub,
                             "features": json.loads(sub.get("features_json") or "{}")},
            "quota": quota,
            "features": features, "documents": docs,
            "bot_url": f"/b/{t['slug']}"}


@router.get("/api/tenant/documents")
def tenant_documents(request: Request):
    """已挂载知识库文档列表(含知识块/实体计数)。"""
    t, _ = _tenant_ctx(request)
    with get_db() as db:
        kb_ids = _tenant_kb_ids(db, t["id"])
        if not kb_ids:
            return []
        ph = ",".join("?" * len(kb_ids))
        rows = db.execute(
            "SELECT d.id, d.kb_id, d.filename, d.title, d.status, d.uploaded_at, "
            "(SELECT COUNT(*) FROM knowledge_chunks c WHERE c.doc_id=d.id) AS chunks, "
            "(SELECT COUNT(*) FROM entities e WHERE e.doc_id=d.id) AS entities "
            f"FROM documents d WHERE d.kb_id IN ({ph}) ORDER BY d.id", kb_ids).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/tenant/documents")
async def tenant_upload(request: Request, file: UploadFile = File(...), title: str = Form("")):
    """上传课程资料(支持 PDF):解析 → 切块向量化 → 本体抽取,Bot 立即可基于新资料回答。
    专业版功能:免费版返回 402 引导升级。同名文件自动重建(RAG 索引同步刷新)。"""
    from ..core import config as core_config
    from ..core.ingest.chunk import ingest_text
    from ..core.ingest.parse import parse_upload
    t, features = _tenant_ctx(request)
    with get_db() as db0:
        if not tenancy.is_active(db0, t["id"]):
            raise HTTPException(status_code=402,
                                detail="服务未开通:请先选购套餐并完成支付")
    if not features.get("rag_manage"):
        raise HTTPException(status_code=402,
                            detail="课程资料管理需要订阅套餐,请先开通")
    with get_db() as db:
        kb_ids = _tenant_kb_ids(db, t["id"])
        if not kb_ids:
            raise HTTPException(status_code=400, detail="租户知识库未初始化")
        kb_id = kb_ids[0]
    raw = await file.read()
    try:
        text = parse_upload(file.filename, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    (core_config.UPLOAD_DIR / f"kb{kb_id}_{file.filename}").write_bytes(raw)
    doc_title = title or (file.filename or "资料").rsplit(".", 1)[0]
    with get_db() as db:
        stats = ingest_text(db, kb_id, file.filename, doc_title, text)
    return {"ok": True, "filename": file.filename, "stats": stats}


@router.delete("/api/tenant/documents/{doc_id}")
def tenant_delete_document(doc_id: int, request: Request):
    """删除文档并同步清理其知识块/实体/规则(RAG 索引同步刷新)。"""
    from ..core.ingest.chunk import clear_document_knowledge
    t, features = _tenant_ctx(request)
    with get_db() as db0:
        if not tenancy.is_active(db0, t["id"]):
            raise HTTPException(status_code=402,
                                detail="服务未开通:请先选购套餐并完成支付")
    if not features.get("rag_manage"):
        raise HTTPException(status_code=402, detail="课程资料管理需要订阅套餐,请先开通")
    with get_db() as db:
        kb_ids = _tenant_kb_ids(db, t["id"])
        doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc or doc["kb_id"] not in kb_ids:
            raise HTTPException(status_code=404, detail="文档不存在或不属于本租户")
        clear_document_knowledge(db, doc_id)
        db.execute("DELETE FROM relations WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM entities WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM rules WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return {"ok": True}


@router.get("/api/tenant/sessions")
def tenant_sessions(request: Request, date_from: str = "", date_to: str = "",
                    limit: int = 100):
    """本租户对话记录(按时间筛选);仅返回本租户会话。"""
    t, _ = _tenant_ctx(request)
    sql = ("SELECT s.id, s.created_at, s.updated_at, "
           "(SELECT COUNT(*) FROM messages g WHERE g.session_id=s.id) AS msgs "
           "FROM sessions s WHERE s.tenant_id=?")
    args: list = [t["id"]]
    if date_from:
        sql += " AND s.updated_at >= ?"
        args.append(date_from + " 00:00:00")
    if date_to:
        sql += " AND s.updated_at <= ?"
        args.append(date_to + " 23:59:59")
    sql += " ORDER BY s.updated_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as db:
        rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/tenant/sessions/{sid}/messages")
def tenant_session_messages(sid: str, request: Request):
    """会话消息明细:脱敏(手机号/邮箱/身份证号打码),且仅限本租户会话。"""
    t, _ = _tenant_ctx(request)
    with get_db() as db:
        s = db.execute("SELECT tenant_id FROM sessions WHERE id=?", (sid,)).fetchone()
        if not s or s["tenant_id"] != t["id"]:
            raise HTTPException(status_code=404, detail="会话不存在")
        rows = db.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return [{"role": r["role"], "content": tenancy.mask_text(r["content"]),
             "created_at": r["created_at"]} for r in rows]


@router.get("/api/tenant/stats")
def tenant_stats(request: Request):
    """用量统计:总对话次数、活跃用户量(会话数)、近14日趋势。"""
    from datetime import datetime, timedelta, timezone
    t, _ = _tenant_ctx(request)
    cst = timezone(timedelta(hours=8))
    today = datetime.now(cst).date()
    with get_db() as db:
        totals = db.execute(
            "SELECT (SELECT COUNT(*) FROM messages m JOIN sessions s ON s.id=m.session_id "
            "        WHERE s.tenant_id=? AND m.role='user') AS chats, "
            "       (SELECT COUNT(*) FROM sessions WHERE tenant_id=?) AS sessions",
            (t["id"], t["id"])).fetchone()
        trend = []
        for i in range(13, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            n = db.execute(
                "SELECT COUNT(*) FROM sessions WHERE tenant_id=? AND substr(created_at,1,10)=?",
                (t["id"], d)).fetchone()[0]
            trend.append({"date": d, "count": n})
        quota = tenancy.quota_state(db, t["id"])
    return {"chats": totals["chats"], "active_users": totals["sessions"],
            "trend": trend, "quota": quota}
