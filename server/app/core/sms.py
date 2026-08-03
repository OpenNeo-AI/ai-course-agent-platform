"""手机验证码服务(参照 OpenNeo server/utils/smsService.js 移植):
阿里云 Dysmsapi POP V1.0 手动 HMAC-SHA1 签名 HTTP 调用,零 SDK 依赖。

- 未配置 ALIYUN_ACCESS_KEY_ID 时进入演示模式:验证码写入日志并随响应返回,
  保证评审/本地环境可走通完整流程(响应中明确标注 demo)。
- 验证码存 sms_codes 表:5 分钟有效;同号码 60 秒 1 条、每小时 ≤5 条;
  校验成功即作废。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from . import config
from .db import get_db

log = logging.getLogger(__name__)

CODE_TTL_SECONDS = 300          # 验证码有效期 5 分钟
RESEND_INTERVAL = 60            # 同号码重发间隔
HOURLY_LIMIT = 5                # 同号码每小时上限

_UTC = timezone.utc


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def is_configured() -> bool:
    return bool(config.env("ALIYUN_ACCESS_KEY_ID") and config.env("ALIYUN_ACCESS_KEY_SECRET"))


def _percent(s: str) -> str:
    return urllib.parse.quote(str(s), safe="~")


def _sign(params: dict, secret: str) -> str:
    """阿里云 POP V1.0 签名(HMAC-SHA1 + Base64),与 smsService.js 一致。"""
    qs = "&".join(f"{_percent(k)}={_percent(params[k])}" for k in sorted(params))
    string_to_sign = "POST&" + _percent("/") + "&" + _percent(qs)
    digest = hmac.new((secret + "&").encode("utf-8"),
                      string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _send_aliyun(phone: str, code: str) -> tuple[bool, str]:
    params = {
        "AccessKeyId": config.env("ALIYUN_ACCESS_KEY_ID") or "",
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": config.env("ALIYUN_SMS_REGION_ID") or "cn-hangzhou",
        "SignName": config.env("ALIYUN_SMS_SIGN_NAME") or "",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "TemplateCode": config.env("ALIYUN_SMS_TEMPLATE_CODE") or "",
        "TemplateParam": f'{{"code":"{code}"}}',
        "Timestamp": datetime.now(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    params["Signature"] = _sign(params, config.env("ALIYUN_ACCESS_KEY_SECRET") or "")
    endpoint = "https://" + (config.env("ALIYUN_SMS_ENDPOINT") or "dysmsapi.aliyuncs.com")
    try:
        resp = httpx.post(endpoint, data=params, timeout=15)
        body = resp.json()
        if body.get("Code") == "OK":
            return True, "ok"
        log.warning("阿里云短信发送失败: %s", body)
        return False, body.get("Message") or body.get("Code") or "发送失败"
    except Exception as e:  # noqa: BLE001
        log.warning("阿里云短信请求异常: %s", e)
        return False, f"短信网关异常({type(e).__name__})"


def send_code(phone: str) -> dict:
    """发送验证码;返回 {ok, demo?, code?(仅演示模式), error?}。"""
    import re
    if not re.fullmatch(r"1[3-9]\d{9}", phone or ""):
        return {"ok": False, "error": "手机号格式不正确"}
    now = datetime.now(timezone(timedelta(hours=8)))
    with get_db() as db:
        last = db.execute("SELECT created_at FROM sms_codes WHERE phone=? "
                          "ORDER BY id DESC LIMIT 1", (phone,)).fetchone()
        if last:
            try:
                t = datetime.strptime(last["created_at"], "%Y-%m-%d %H:%M:%S")
                t = t.replace(tzinfo=timezone(timedelta(hours=8)))
                if (now - t).total_seconds() < RESEND_INTERVAL:
                    return {"ok": False, "error": f"发送过于频繁,请 {RESEND_INTERVAL} 秒后重试"}
            except ValueError:
                pass
        cnt = db.execute("SELECT COUNT(*) FROM sms_codes WHERE phone=? AND created_at>=?",
                         (phone, (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))
                         ).fetchone()[0]
        if cnt >= HOURLY_LIMIT:
            return {"ok": False, "error": "该号码发送次数过多,请 1 小时后重试"}
        code = f"{secrets.randbelow(1000000):06d}"
        db.execute("INSERT INTO sms_codes(phone, code, expires_at, created_at) VALUES(?,?,?,?)",
                   (phone, code,
                    (now + timedelta(seconds=CODE_TTL_SECONDS)).strftime("%Y-%m-%d %H:%M:%S"),
                    _now()))
    if is_configured():
        ok, msg = _send_aliyun(phone, code)
        if not ok:
            return {"ok": False, "error": f"短信发送失败:{msg}"}
        return {"ok": True}
    # 演示模式:未配置短信密钥,验证码随响应返回(页面提示演示环境)
    log.info("SMS 演示模式 → %s 的验证码: %s", phone[:3] + "****" + phone[7:], code)
    return {"ok": True, "demo": True, "code": code}


def verify_code(phone: str, code: str, consume: bool = True) -> bool:
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        row = db.execute("SELECT id, code FROM sms_codes WHERE phone=? AND expires_at>=? "
                         "ORDER BY id DESC LIMIT 1", (phone, now)).fetchone()
        if not row or row["code"] != (code or "").strip():
            return False
        if consume:
            db.execute("DELETE FROM sms_codes WHERE phone=?", (phone,))
        return True
