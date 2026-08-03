"""SaaS 端点:认证(注册/登录/JWT)、套餐订阅、租户管理。

路由分组:
  /api/auth/*      注册、登录、当前用户
  /api/plans       套餐列表(公开,套餐展示页)
  /api/billing/*   订单与支付演示(P2 补充)
  /api/tenant/*    租户 Admin:资料/对话记录/用量(P3 补充)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

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
    """当前登录用户 + 租户 + 订阅 + 当月配额(Portal/Admin 分叉依据)。"""
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
