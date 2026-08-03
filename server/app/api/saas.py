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

from ..core import auth, tenancy
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


@router.post("/api/auth/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    username = (body.get("username") or "").strip().lower()
    password = body.get("password") or ""
    with get_db() as db:
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


@router.post("/api/billing/orders")
async def create_order(request: Request):
    """选套餐 → 创建待支付订单(演示环境默认 mock 渠道)。"""
    from ..core import payments
    user = jwt_user(request)
    tid = _tenant_of(user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    try:
        order = payments.create_order(tid, body.get("plan_code", "pro"),
                                      body.get("channel", "mock"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "order": order}


@router.post("/api/billing/orders/{order_id}/confirm")
def confirm_order(order_id: int, request: Request):
    """模拟支付成功回调:订单置 paid → 订阅升级 → 功能解锁。"""
    from ..core import payments
    user = jwt_user(request)
    tid = _tenant_of(user)
    with get_db() as db:
        order = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
    if not order or order["tenant_id"] != tid:
        raise HTTPException(status_code=404, detail="订单不存在")
    try:
        return {"ok": True, **payments.pay_success(order_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    return {"tenant": t, "subscription": sub, "quota": quota,
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
    if not features.get("rag_manage"):
        raise HTTPException(status_code=402,
                            detail="课程资料管理为专业版功能,请先升级套餐")
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
    if not features.get("rag_manage"):
        raise HTTPException(status_code=402, detail="课程资料管理为专业版功能,请先升级套餐")
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
