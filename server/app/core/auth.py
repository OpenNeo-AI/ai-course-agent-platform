"""用户认证:密码哈希(pbkdf2) + JWT 签发/校验(零新增依赖,pyjwt 已在环境)。

- 密码格式:pbkdf2_sha256$<salt_hex>$<hash_hex>
- JWT 载荷:{sub, username, role, tenant_id, exp};密钥取 JWT_SECRET 环境变量,
  缺省时由 portal token 派生(单机演示足够,生产应显式配置)。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from . import config

_ALGO = "HS256"
_TOKEN_DAYS = 7


def _secret() -> str:
    s = config.env("JWT_SECRET") or ""
    if not s:
        s = "opc-saas:" + config.portal_token()
    # HMAC-SHA256 建议密钥 ≥32 字节:统一摘要派生
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000)
    return f"pbkdf2_sha256${salt}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, hexd = stored.split("$", 2)
        if scheme != "pbkdf2_sha256":
            return False
        h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000)
        return hmac.compare_digest(h.hex(), hexd)
    except Exception:  # noqa: BLE001
        return False


def issue_token(user: dict) -> str:
    """user: {id, username, role, tenant_id}"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),          # pyjwt 要求 sub 为字符串
        "username": user["username"],
        "role": user["role"],
        "tenant_id": user.get("tenant_id"),
        "iat": now,
        "exp": now + timedelta(days=_TOKEN_DAYS),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGO])
        payload["sub"] = int(payload["sub"])
        return payload
    except Exception:  # noqa: BLE001
        return None
