"""FastAPI 主服务:REST 会话接口 + SSE 流式对话 + /mcp 挂载 + 静态前端。

启动:python -m app.main   (监听 .env 的 HOST/PORT,默认 0.0.0.0:7000)
端点:
  POST /api/session          创建会话 {role: student|teacher|platform}
  POST /api/chat             SSE 流式对话 {session_id, text}
                             事件:start / tool(工具进度) / delta(回复分片) / done / error
  *    /mcp                  MCP streamable HTTP(第三方 Agent 接入)
  GET  /api/health           健康检查
  /                          web/dist 静态前端(存在时)
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.routing import Route

from .agent import loop
from .api.portal import router as portal_router
from .core import config
from .mcp_server import mcp_platform
from .mcp_server import mcp_student, mcp_teacher

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

WEB_DIST = config.BASE_DIR.parent / "web" / "dist"

# MCP streamable HTTP:每个智能体一个端点,取子应用纯 ASGI 处理器精确挂载(无重定向);
# 各子应用的 lifespan(会话管理器任务组)由主 lifespan 统一启动。
_mcp_subs = []


def _mcp_asgi(instance):
    instance.settings.streamable_http_path = "/"
    sub = instance.streamable_http_app()
    _mcp_subs.append(sub)
    return _with_channel_auth(sub.routes[0].app)


class _ChannelAuthASGI:
    """MCP 渠道令牌鉴权 ASGI 包装:校验 Authorization: Bearer <ak_...>。
    系统存在有效(未禁用)渠道令牌时,要求携带有效令牌;尚无任何令牌时保持开放(向后兼容)。
    用类封装(而非裸函数),确保 Starlette 视其为 ASGI app 而非 request-response endpoint。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            from .core import db as dbmod
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode("utf-8", "replace")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            with dbmod.get_db() as db:
                active = db.execute(
                    "SELECT COUNT(*) FROM channel_tokens WHERE disabled=0").fetchone()[0]
                valid = None
                if token:
                    valid = db.execute(
                        "SELECT id FROM channel_tokens WHERE token=? AND disabled=0",
                        (token,)).fetchone()
                    if valid:
                        db.execute(
                            "UPDATE channel_tokens SET last_used_at=datetime('now','localtime') "
                            "WHERE id=?", (valid["id"],))
            if active and not valid:
                resp = JSONResponse(
                    {"error": "unauthorized: 无效或缺失的渠道令牌"}, status_code=401)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _with_channel_auth(asgi_app):
    return _ChannelAuthASGI(asgi_app)


_asgi_platform = _mcp_asgi(mcp_platform)
_asgi_student = _mcp_asgi(mcp_student)
_asgi_teacher = _mcp_asgi(mcp_teacher)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from contextlib import AsyncExitStack
    async with AsyncExitStack() as stack:
        for sub in _mcp_subs:
            await stack.enter_async_context(sub.router.lifespan_context(sub))
        yield


app = FastAPI(title="OPC AI Course Advisor", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(portal_router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "opc-course-advisor"}


@app.post("/api/session")
async def create_session(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    role = (body or {}).get("role", "platform")
    if role not in ("student", "teacher", "platform"):
        role = "platform"
    return await asyncio.to_thread(loop.new_session, role)


@app.post("/api/tool")
async def call_tool(request: Request):
    """通用工具端点 {name, args, role}:供 skill 脚本、portal 调试与第三方按 REST 接入。
    role(默认 platform)决定作用域:工具自动在其对接的知识域内检索与计算。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "请求体必须是 JSON: {name, args}"}, status_code=400)
    name = (body or {}).get("name", "")
    args = dict((body or {}).get("args", {}) or {})
    role = (body or {}).get("role") or args.pop("role", None) or "platform"
    from .core import tools as core_tools
    from .core.scope import apply_scope_ask, scope_for_role
    if name == "get_welcome":
        return core_tools.tool_welcome(role)
    scope = await asyncio.to_thread(scope_for_role, role)
    if name == "ask_knowledge":
        args = apply_scope_ask(scope, args)
        if "error" in args:
            return args
    elif name in ("recommend_products", "calculate_fee", "list_products",
                  "get_enrollment_info"):
        args["domain_ids"] = scope["domain_ids"]
    result = await asyncio.to_thread(core_tools.dispatch, name, args)
    return result


@app.post("/api/chat")
async def chat(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "请求体必须是 JSON: {session_id, text}"}, status_code=400)
    session_id = (body or {}).get("session_id", "")
    text = (body or {}).get("text", "")
    if not session_id:
        return JSONResponse({"error": "缺少 session_id"}, status_code=400)

    async def gen():
        yield {"event": "start", "data": json.dumps({"session_id": session_id},
                                                    ensure_ascii=False)}
        it = loop.run_turn_stream(session_id, text)
        sentinel = object()
        try:
            while True:
                ev = await asyncio.to_thread(next, it, sentinel)
                if ev is sentinel:
                    break
                t = ev.get("type")
                if t == "delta":
                    yield {"event": "delta",
                           "data": json.dumps({"text": ev["text"]}, ensure_ascii=False)}
                elif t == "tool":
                    yield {"event": "tool",
                           "data": json.dumps({"name": ev["name"], "summary": ev["summary"]},
                                              ensure_ascii=False)}
                elif t == "done":
                    yield {"event": "done",
                           "data": json.dumps({"session_id": session_id, "state": ev.get("state"),
                                               "reset": ev.get("reset"), "cite": ev.get("cite"),
                                               "cite_raw": ev.get("cite_raw")},
                                              ensure_ascii=False)}
                elif t == "error":
                    yield {"event": "error",
                           "data": json.dumps({"error": ev.get("error")}, ensure_ascii=False)}
        except Exception as e:  # noqa: BLE001
            log.exception("chat 异常")
            yield {"event": "error",
                   "data": json.dumps({"error": f"服务异常,请稍后重试。({type(e).__name__})"},
                                      ensure_ascii=False)}

    return EventSourceResponse(gen())


# MCP 端点:通用 /mcp,学生 /mcp/student,教师 /mcp/teacher(各含尾斜杠别名)
for _path, _asgi in (("/mcp", _asgi_platform),
                     ("/mcp/student", _asgi_student),
                     ("/mcp/teacher", _asgi_teacher)):
    app.router.routes.append(Route(_path, _asgi))
    app.router.routes.append(Route(_path + "/", _asgi))

# 静态前端 + SPA 回退:存在的文件直接返回,其余路径返回 index.html(支持 /s /t /c 前端路由)
if WEB_DIST.exists():
    from fastapi.responses import FileResponse

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        target = (WEB_DIST / path).resolve()
        if path and target.is_file() and str(target).startswith(str(WEB_DIST.resolve())):
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.host(), port=config.port(), log_level="info")
