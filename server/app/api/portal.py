"""Portal 管理后端:文档管理 / 本体浏览 / 配置编辑 / 会话查看。

鉴权:除 login 外全部需要 Authorization: Bearer <portal_token>
(令牌见 config.portal_token:.env PORTAL_TOKEN 或 data/config/portal_token.txt)。
配置编辑直接落盘文件,热加载由 config 的 mtime 缓存保证,无需重启。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from ..core import config, llm, quality
from ..core.db import get_db, list_domains, list_kbs, log_action
from ..core.ingest.chunk import clear_document_knowledge, ingest_text
from ..core.ontology.graph import build_graph, derive_all, derive_links, object_detail

router = APIRouter(prefix="/api/portal", tags=["portal"])


def _principal(request: Request) -> dict:
    """身份解析:超管(静态 portal token / superadmin 账户)或租户管理员。
    返回 {super: bool, tenant_id: int|None, username: str}。
    统一工作台的作用域基础:租户仅见/仅能操作本租户的知识域与会话。"""
    from ..core import auth as core_auth
    authh = request.headers.get("authorization", "")
    token = authh[7:].strip() if authh.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="未授权:令牌缺失")
    if token == config.portal_token():
        return {"super": True, "tenant_id": None, "username": "portal"}
    payload = core_auth.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="未授权:令牌无效或已过期")
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id=?", (payload.get("sub"),)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="未授权:用户不存在")
    if row["role"] == "superadmin":
        return {"super": True, "tenant_id": None, "username": row["username"]}
    if not row["tenant_id"]:
        raise HTTPException(status_code=403, detail="用户未归属租户")
    return {"super": False, "tenant_id": row["tenant_id"], "username": row["username"]}


def _auth(request: Request) -> None:
    _principal(request)


def _require_super(request: Request) -> dict:
    p = _principal(request)
    if not p["super"]:
        raise HTTPException(status_code=403, detail="需要平台超管权限")
    return p


# ---------- 租户作用域辅助 ----------

def _tenant_domain_ids(db, tenant_id: int) -> list[int]:
    return [r["id"] for r in db.execute(
        "SELECT id FROM domains WHERE tenant_id=?", (tenant_id,))]


def _tenant_kb_ids(db, tenant_id: int) -> list[int]:
    return [r["id"] for r in db.execute(
        "SELECT k.id FROM kbs k JOIN domains d ON d.id=k.domain_id WHERE d.tenant_id=?",
        (tenant_id,))]


def _check_domain(db, p: dict, dom_id: int) -> None:
    if p["super"]:
        return
    row = db.execute("SELECT tenant_id FROM domains WHERE id=?", (dom_id,)).fetchone()
    if not row or row["tenant_id"] != p["tenant_id"]:
        raise HTTPException(status_code=403, detail="无权操作该知识域")


def _check_kb(db, p: dict, kb_id: int) -> None:
    if p["super"]:
        return
    row = db.execute(
        "SELECT d.tenant_id AS t FROM kbs k JOIN domains d ON d.id=k.domain_id WHERE k.id=?",
        (kb_id,)).fetchone()
    if not row or row["t"] != p["tenant_id"]:
        raise HTTPException(status_code=403, detail="无权操作该知识库")


def _check_session_owner(db, p: dict, sid: str) -> None:
    row = db.execute("SELECT tenant_id FROM sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="会话不存在")
    if not p["super"] and row["tenant_id"] != p["tenant_id"]:
        raise HTTPException(status_code=403, detail="无权查看该会话")


def _check_entity_owner(db, p: dict, eid: int) -> None:
    if p["super"]:
        return
    row = db.execute(
        "SELECT dom.tenant_id AS t FROM entities e JOIN documents d ON d.id=e.doc_id "
        "JOIN kbs k ON k.id=d.kb_id JOIN domains dom ON dom.id=k.domain_id WHERE e.id=?",
        (eid,)).fetchone()
    if not row or row["t"] != p["tenant_id"]:
        raise HTTPException(status_code=403, detail="无权操作该对象")


def _check_rule_owner(db, p: dict, rid: int) -> None:
    if p["super"]:
        return
    row = db.execute(
        "SELECT dom.tenant_id AS t FROM rules r JOIN documents d ON d.id=r.doc_id "
        "JOIN kbs k ON k.id=d.kb_id JOIN domains dom ON dom.id=k.domain_id WHERE r.id=?",
        (rid,)).fetchone()
    if not row or row["t"] != p["tenant_id"]:
        raise HTTPException(status_code=403, detail="无权操作该规则")


def _tenant_features(db, p: dict) -> dict:
    """租户当前套餐功能位(超管返回空 dict)。"""
    if p["super"]:
        return {}
    from ..core.tenancy import subscription_of
    return json.loads(subscription_of(db, p["tenant_id"]).get("features_json") or "{}")


def _require_active_sub(db, p: dict) -> None:
    """租户须已开通订阅(支付生效)才可使用业务功能。"""
    if p["super"]:
        return
    from ..core.tenancy import is_active
    if not is_active(db, p["tenant_id"]):
        raise HTTPException(status_code=402,
                            detail="服务未开通:请先在工作台「套餐订阅」中选购套餐并完成支付")


def _require_feature(db, p: dict, feature: str, label: str) -> None:
    """套餐功能门禁:当前套餐未含该功能位时返回 402 引导升级。"""
    _require_active_sub(db, p)
    if p["super"]:
        return
    if not _tenant_features(db, p).get(feature):
        raise HTTPException(status_code=402,
                            detail=f"「{label}」需更高套餐解锁,请先升级")


# ---------- 登录 ----------

@router.post("/login")
async def login(request: Request):
    """用户名 + 密码登录;校验通过后下发 portal token 作为后续 Bearer 凭证。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    for acc in config.portal_accounts():
        if username == acc["username"] and password == acc["password"]:
            return {"ok": True, "token": config.portal_token()}
    # 兼容旧的单令牌登录(直接提交 token)
    if body.get("token") and body.get("token") == config.portal_token():
        return {"ok": True, "token": config.portal_token()}
    raise HTTPException(status_code=401, detail="账户或密码错误")


# ---------- 智能体对接配置(agents.yaml) ----------

@router.get("/agents", dependencies=[Depends(_auth)])
def get_agents(request: Request):
    _require_super(request)
    return config.agents_config()


@router.put("/agents", dependencies=[Depends(_auth)])
async def put_agents(request: Request):
    """按角色合并更新对接配置并重写 agents.yaml(热加载生效)。平台超管。
    请求体:{"student": {"identity": "student", "domains": ["domain-a"]}, ...}"""
    _require_super(request)
    body = await request.json() or {}
    cfg = config.agents_config()
    for role, val in body.items():
        if not isinstance(val, dict):
            continue
        entry = cfg.setdefault(role, {})
        if "identity" in val:
            if val["identity"]:
                entry["identity"] = val["identity"]
            else:
                entry.pop("identity", None)
        if "domains" in val and isinstance(val["domains"], list):
            entry["domains"] = [str(d) for d in val["domains"]]
            entry.pop("kbs", None)   # 升级为知识域语法
        if "model" in val:
            if val["model"]:
                entry["model"] = str(val["model"])
            else:
                entry.pop("model", None)   # 置空 = 跟随系统默认模型
        if "capabilities" in val and isinstance(val["capabilities"], dict):
            caps = entry.setdefault("capabilities", {})
            for k in ("lead_capture", "quality_check"):
                if k in val["capabilities"]:
                    caps[k] = bool(val["capabilities"][k])
    header = ("# 智能体引用范围与能力定义:\n"
              "# - domains:对接的知识域,范围外知识域不参与该智能体的检索、推荐与计算。\n"
              "# - capabilities:扩展能力开关(lead_capture/quality_check/reminder),portal 可视化配置。\n")
    (config.CONFIG_DIR / "agents.yaml").write_text(
        header + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return {"ok": True, "agents": cfg}


# ---------- 知识域管理 ----------

@router.get("/domains", dependencies=[Depends(_auth)])
def get_domains(request: Request):
    p = _principal(request)
    with get_db() as db:
        rows = list_domains(db)
    if not p["super"]:
        rows = [d for d in rows if d.get("tenant_id") == p["tenant_id"]]
    return rows


@router.post("/domains", dependencies=[Depends(_auth)])
async def create_domain(request: Request):
    p = _principal(request)
    body = await request.json() or {}
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少知识域名称")
    import secrets
    with get_db() as db:
        _require_feature(db, p, "domains", "知识域管理")
        code = f"domain-{secrets.token_hex(3)}"
        while db.execute("SELECT 1 FROM domains WHERE code=?", (code,)).fetchone():
            code = f"domain-{secrets.token_hex(3)}"
        cur = db.execute(
            "INSERT INTO domains(code, name, description, tenant_id) VALUES(?,?,?,?)",
            (code, name, body.get("description", ""), p["tenant_id"]))
    return {"ok": True, "id": cur.lastrowid, "code": code}


@router.put("/domains/{dom_id}", dependencies=[Depends(_auth)])
async def update_domain(dom_id: int, request: Request):
    p = _principal(request)
    body = await request.json() or {}
    fields, args = [], []
    for k in ("name", "description"):
        if k in body:
            fields.append(f"{k}=?")
            args.append(body[k])
    # semantics(知识域类型)已废弃:忽略旧端传入的该字段
    if not fields:
        raise HTTPException(status_code=400, detail="无可更新字段")
    args.append(dom_id)
    with get_db() as db:
        _check_domain(db, p, dom_id)
        _require_feature(db, p, "domains", "知识域管理")
        cur = db.execute(f"UPDATE domains SET {', '.join(fields)} WHERE id=?", args)
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="知识域不存在")
    return {"ok": True}


@router.delete("/domains/{dom_id}", dependencies=[Depends(_auth)])
def delete_domain(dom_id: int, request: Request):
    p = _principal(request)
    with get_db() as db:
        dom = db.execute("SELECT * FROM domains WHERE id=?", (dom_id,)).fetchone()
        if not dom:
            raise HTTPException(status_code=404, detail="知识域不存在")
        _check_domain(db, p, dom_id)
        _require_feature(db, p, "domains", "知识域管理")
        for kb in db.execute("SELECT id FROM kbs WHERE domain_id=?", (dom_id,)).fetchall():
            for d in db.execute("SELECT id FROM documents WHERE kb_id=?", (kb["id"],)).fetchall():
                clear_document_knowledge(db, d["id"])
                db.execute("DELETE FROM relations WHERE doc_id=?", (d["id"],))
                db.execute("DELETE FROM entities WHERE doc_id=?", (d["id"],))
                db.execute("DELETE FROM rules WHERE doc_id=?", (d["id"],))
                db.execute("DELETE FROM documents WHERE id=?", (d["id"],))
            db.execute("DELETE FROM kbs WHERE id=?", (kb["id"],))
        db.execute("DELETE FROM edges WHERE domain_id=?", (dom_id,))
        db.execute("DELETE FROM domains WHERE id=?", (dom_id,))
    return {"ok": True}


# ---------- 知识库管理 ----------

@router.get("/kbs", dependencies=[Depends(_auth)])
def get_kbs(request: Request, domain_id: int = 0):
    p = _principal(request)
    with get_db() as db:
        rows = list_kbs(db, domain_id or None)
        if not p["super"]:
            dom_ids = set(_tenant_domain_ids(db, p["tenant_id"]))
            rows = [k for k in rows if k.get("domain_id") in dom_ids]
    return rows


@router.post("/kbs", dependencies=[Depends(_auth)])
async def create_kb(request: Request):
    p = _principal(request)
    body = await request.json() or {}
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少知识库名称")
    domain_id = body.get("domain_id")
    if not domain_id:
        raise HTTPException(status_code=400, detail="缺少所属知识域 domain_id")
    import secrets
    with get_db() as db:
        dom = db.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
        if not dom:
            raise HTTPException(status_code=404, detail="知识域不存在")
        _check_domain(db, p, domain_id)
        _require_feature(db, p, "domains", "知识域管理")
        code = body.get("code", "").strip()
        if not code:
            code = f"kb-{secrets.token_hex(3)}"
            while db.execute("SELECT 1 FROM kbs WHERE code=?", (code,)).fetchone():
                code = f"kb-{secrets.token_hex(3)}"
        elif db.execute("SELECT 1 FROM kbs WHERE code=?", (code,)).fetchone():
            raise HTTPException(status_code=400, detail=f"知识库标识 {code} 已存在")
        cur = db.execute(
            "INSERT INTO kbs(code, name, description, domain_id) VALUES(?,?,?,?)",
            (code, name, body.get("description", ""), domain_id))
        kb_id = cur.lastrowid
    return {"ok": True, "id": kb_id, "code": code}


@router.put("/kbs/{kb_id}", dependencies=[Depends(_auth)])
async def update_kb(kb_id: int, request: Request):
    p = _principal(request)
    body = await request.json() or {}
    fields, args = [], []
    for k in ("name", "description"):
        if k in body:
            fields.append(f"{k}=?")
            args.append(body[k])
    if body.get("domain_id"):
        with get_db() as db0:
            dom = db0.execute("SELECT * FROM domains WHERE id=?",
                              (body["domain_id"],)).fetchone()
            if dom:
                _check_domain(db0, p, body["domain_id"])
        if not dom:
            raise HTTPException(status_code=404, detail="目标知识域不存在")
        fields.append("domain_id=?")
        args.append(dom["id"])
    if not fields:
        raise HTTPException(status_code=400, detail="无可更新字段")
    args.append(kb_id)
    with get_db() as db:
        _check_kb(db, p, kb_id)
        _require_feature(db, p, "domains", "知识域管理")
        cur = db.execute(f"UPDATE kbs SET {', '.join(fields)} WHERE id=?", args)
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="知识库不存在")
    return {"ok": True}


@router.delete("/kbs/{kb_id}", dependencies=[Depends(_auth)])
def delete_kb(kb_id: int, request: Request):
    p = _principal(request)
    with get_db() as db:
        _check_kb(db, p, kb_id)
        _require_feature(db, p, "domains", "知识域管理")
        docs = db.execute("SELECT id FROM documents WHERE kb_id=?", (kb_id,)).fetchall()
        for d in docs:
            clear_document_knowledge(db, d["id"])
            db.execute("DELETE FROM relations WHERE doc_id=?", (d["id"],))
            db.execute("DELETE FROM entities WHERE doc_id=?", (d["id"],))
            db.execute("DELETE FROM rules WHERE doc_id=?", (d["id"],))
            db.execute("DELETE FROM documents WHERE id=?", (d["id"],))
        cur = db.execute("DELETE FROM kbs WHERE id=?", (kb_id,))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="知识库不存在")
    return {"ok": True}


# ---------- 文档管理 ----------

@router.get("/documents", dependencies=[Depends(_auth)])
def list_documents(request: Request, kb_id: int = 0):
    p = _principal(request)
    sql = ("SELECT d.id, k.name AS kb_name, d.kb_id, "
           "d.filename, d.title, d.status, d.uploaded_at, "
           "(SELECT COUNT(*) FROM knowledge_chunks c WHERE c.doc_id=d.id) AS chunks, "
           "(SELECT COUNT(*) FROM entities e WHERE e.doc_id=d.id) AS entities "
           "FROM documents d LEFT JOIN kbs k ON k.id=d.kb_id")
    args: list = []
    if kb_id:
        sql += " WHERE d.kb_id=?"
        args.append(kb_id)
    sql += " ORDER BY d.id"
    with get_db() as db:
        rows = [dict(r) for r in db.execute(sql, args).fetchall()]
        if not p["super"]:
            kb_ids = set(_tenant_kb_ids(db, p["tenant_id"]))
            rows = [r for r in rows if r["kb_id"] in kb_ids]
    return rows


@router.post("/documents", dependencies=[Depends(_auth)])
async def upload_document(request: Request, file: UploadFile = File(...),
                          kb_id: int = Form(...), title: str = Form("")):
    """上传知识文档(.txt/.docx/.doc/.pdf)→ 解析 → 切块向量化 → ontology 抽取。
    归属知识库由 kb_id 指定(文档经 知识库→知识域 归属);同名文件自动重建。
    租户上传受专业版 rag_manage 门禁(免费版 402 引导升级)。"""
    from ..core.ingest.parse import parse_upload
    p = _principal(request)
    with get_db() as db:
        kb = db.execute("SELECT * FROM kbs WHERE id=?", (kb_id,)).fetchone()
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        _check_kb(db, p, kb_id)
        _require_active_sub(db, p)
        if not p["super"] and not _tenant_features(db, p).get("rag_manage"):
            raise HTTPException(status_code=402,
                                detail="课程资料管理需要订阅套餐,请先开通")
    raw = await file.read()
    try:
        text = parse_upload(file.filename, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    (config.UPLOAD_DIR / f"kb{kb_id}_{file.filename}").write_bytes(raw)
    doc_title = title or file.filename.rsplit(".", 1)[0]
    with get_db() as db:
        stats = ingest_text(db, kb_id, file.filename, doc_title, text)
    return {"ok": True, "filename": file.filename, "kb_id": kb_id, "stats": stats}


@router.delete("/documents/{doc_id}", dependencies=[Depends(_auth)])
def delete_document(doc_id: int, request: Request):
    p = _principal(request)
    with get_db() as db:
        row = db.execute(
            "SELECT dom.tenant_id AS t FROM documents d JOIN kbs k ON k.id=d.kb_id "
            "JOIN domains dom ON dom.id=k.domain_id WHERE d.id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="文档不存在")
        if not p["super"]:
            if row["t"] != p["tenant_id"]:
                raise HTTPException(status_code=403, detail="无权操作该文档")
            _require_active_sub(db, p)
            if not _tenant_features(db, p).get("rag_manage"):
                raise HTTPException(status_code=402,
                                    detail="课程资料管理需要订阅套餐,请先开通")
        clear_document_knowledge(db, doc_id)
        db.execute("DELETE FROM relations WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM entities WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM rules WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return {"ok": True}


# ---------- 本体浏览与维护 ----------

@router.get("/entities", dependencies=[Depends(_auth)])
def list_entities(request: Request, domain: str = "", type: str = "", status: str = ""):
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "ontology", "本体图谱")
        sql = ("SELECT e.id, dm.code AS domain_code, dm.name AS domain_name, "
               "e.type, e.name, e.attrs_json, e.chapter, e.status, e.raw_excerpt, d.filename "
               "FROM entities e JOIN documents d ON d.id=e.doc_id "
               "JOIN kbs k ON k.id=d.kb_id JOIN domains dm ON dm.id=k.domain_id WHERE 1=1")
        args: list = []
        if not p["super"]:
            sql += " AND dm.tenant_id=?"
            args.append(p["tenant_id"])
        if domain:
            sql += " AND dm.code=?"
            args.append(domain)
        if type:
            sql += " AND e.type=?"
            args.append(type)
        if status:
            sql += " AND e.status=?"
            args.append(status)
        sql += " ORDER BY k.domain_id, e.type, e.id"
        rows = db.execute(sql, args).fetchall()
    return [{**dict(r), "attrs": json.loads(r["attrs_json"] or "{}")} for r in rows]


@router.get("/rules", dependencies=[Depends(_auth)])
def list_rules(request: Request, domain: str = "", kind: str = ""):
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "ontology", "本体图谱")
        sql = ("SELECT r.id, dm.code AS domain_code, dm.name AS domain_name, "
               "r.kind, r.scope_json, r.params_json, r.chapter, r.status, r.raw_excerpt, d.filename "
               "FROM rules r JOIN documents d ON d.id=r.doc_id "
               "JOIN kbs k ON k.id=d.kb_id JOIN domains dm ON dm.id=k.domain_id WHERE 1=1")
        args: list = []
        if not p["super"]:
            sql += " AND dm.tenant_id=?"
            args.append(p["tenant_id"])
        if domain:
            sql += " AND dm.code=?"
            args.append(domain)
        if kind:
            sql += " AND r.kind=?"
            args.append(kind)
        sql += " ORDER BY k.domain_id, r.id"
        rows = db.execute(sql, args).fetchall()
    return [{**dict(r),
             "scope": json.loads(r["scope_json"] or "{}"),
             "params": json.loads(r["params_json"] or "{}")} for r in rows]


@router.get("/relations", dependencies=[Depends(_auth)])
def list_relations(request: Request, domain: str = ""):
    p = _principal(request)
    with get_db() as db0:
        _require_feature(db0, p, "ontology", "本体图谱")
    sql = ("SELECT rel.id, dm.code AS domain_code, s.name AS src, rel.rel, t.name AS dst, rel.chapter "
           "FROM relations rel "
           "JOIN entities s ON s.id=rel.src_id JOIN entities t ON t.id=rel.dst_id "
           "JOIN documents d ON d.id=s.doc_id JOIN kbs k ON k.id=d.kb_id "
           "JOIN domains dm ON dm.id=k.domain_id WHERE 1=1")
    args: list = []
    if not p["super"]:
        sql += " AND dm.tenant_id=?"
        args.append(p["tenant_id"])
    if domain:
        sql += " AND dm.code=?"
        args.append(domain)
    with get_db() as db:
        rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@router.post("/entities/{eid}/confirm", dependencies=[Depends(_auth)])
def confirm_entity(eid: int, request: Request):
    p = _principal(request)
    with get_db() as db:
        _check_entity_owner(db, p, eid)
        cur = db.execute("UPDATE entities SET status='confirmed' WHERE id=?", (eid,))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="实体不存在")
        row = db.execute("SELECT type, name FROM entities WHERE id=?", (eid,)).fetchone()
        log_action(db, "confirm_object", f"{row['type']}:{row['name']}", f"e{eid}")
    return {"ok": True}


@router.put("/entities/{eid}", dependencies=[Depends(_auth)])
async def update_entity(eid: int, request: Request):
    p = _principal(request)
    body = await request.json()
    attrs = (body or {}).get("attrs")
    name = (body or {}).get("name")
    if attrs is None:
        raise HTTPException(status_code=400, detail="缺少 attrs")
    with get_db() as db:
        row = db.execute("SELECT id FROM entities WHERE id=?", (eid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="实体不存在")
        _check_entity_owner(db, p, eid)
        if name:
            db.execute("UPDATE entities SET name=?, attrs_json=?, status='edited' WHERE id=?",
                       (name, json.dumps(attrs, ensure_ascii=False), eid))
        else:
            db.execute("UPDATE entities SET attrs_json=?, status='edited' WHERE id=?",
                       (json.dumps(attrs, ensure_ascii=False), eid))
        log_action(db, "edit_object", f"e{eid}", (name or "attrs") )
    return {"ok": True}


@router.put("/rules/{rid}", dependencies=[Depends(_auth)])
async def update_rule(rid: int, request: Request):
    p = _principal(request)
    body = await request.json()
    params = (body or {}).get("params")
    if params is None:
        raise HTTPException(status_code=400, detail="缺少 params")
    with get_db() as db:
        _check_rule_owner(db, p, rid)
        cur = db.execute("UPDATE rules SET params_json=?, status='edited' WHERE id=?",
                         (json.dumps(params, ensure_ascii=False), rid))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="规则不存在")
        log_action(db, "edit_rule", f"r{rid}", json.dumps(params, ensure_ascii=False)[:200])
    return {"ok": True}


# ---------- 本体图谱 ----------

@router.get("/ontology/schema", dependencies=[Depends(_auth)])
def get_ontology_schema():
    return config.ontology_schema()


@router.get("/ontology/graph", dependencies=[Depends(_auth)])
def ontology_graph(request: Request, domain: str = "", types: str = "", q: str = ""):
    p = _principal(request)
    type_list = [t for t in types.split(",") if t] if types else None
    with get_db() as db:
        _require_feature(db, p, "ontology", "本体图谱")
        if p["super"]:
            return build_graph(db, domain or None, type_list, q or None)
        codes = [r["code"] for r in db.execute(
            "SELECT code FROM domains WHERE tenant_id=?", (p["tenant_id"],))]
        if domain and domain not in codes:
            raise HTTPException(status_code=403, detail="无权查看该知识域图谱")
        if domain:
            return build_graph(db, domain, type_list, q or None)
        # 未指定知识域:合并本租户全部知识域
        merged = {"nodes": {}, "edges": [], "stats": {}}
        for c in codes:
            g = build_graph(db, c, type_list, q or None)
            merged["nodes"].update(g.get("nodes") or {})
            merged["edges"].extend(g.get("edges") or [])
            for k, v in (g.get("stats") or {}).items():
                merged["stats"][k] = merged["stats"].get(k, 0) + v if isinstance(v, int) else v
        return merged


@router.get("/ontology/objects/{node_id}", dependencies=[Depends(_auth)])
def ontology_object(node_id: str, request: Request):
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "ontology", "本体图谱")
        obj = object_detail(db, node_id)
        if not obj:
            raise HTTPException(status_code=404, detail="对象不存在")
        if not p["super"]:
            dom_id = _node_domain(db, node_id)
            if dom_id:
                _check_domain(db, p, dom_id)
    return obj


def _node_domain(db, node_id: str) -> int | None:
    if node_id.startswith("dom") and node_id[3:].isdigit():
        return int(node_id[3:])
    if node_id.startswith("e") and node_id[1:].isdigit():
        row = db.execute("SELECT k.domain_id AS v FROM entities e "
                         "JOIN documents d ON d.id=e.doc_id JOIN kbs k ON k.id=d.kb_id "
                         "WHERE e.id=?", (int(node_id[1:]),)).fetchone()
        return row["v"] if row else None
    if node_id.startswith("r") and node_id[1:].isdigit():
        row = db.execute("SELECT k.domain_id AS v FROM rules r "
                         "JOIN documents d ON d.id=r.doc_id JOIN kbs k ON k.id=d.kb_id "
                         "WHERE r.id=?", (int(node_id[1:]),)).fetchone()
        return row["v"] if row else None
    if node_id.startswith("d") and node_id[1:].isdigit():
        row = db.execute("SELECT k.domain_id AS v FROM documents d "
                         "JOIN kbs k ON k.id=d.kb_id WHERE d.id=?",
                         (int(node_id[1:]),)).fetchone()
        return row["v"] if row else None
    return None


@router.post("/ontology/links", dependencies=[Depends(_auth)])
async def add_link(request: Request):
    """人工创建类型化链接(rel 必须是 Schema 中的链接类型代码)。"""
    p = _principal(request)
    body = await request.json() or {}
    src, dst, rel = body.get("src_node", ""), body.get("dst_node", ""), body.get("rel", "")
    if not (src and dst and rel):
        raise HTTPException(status_code=400, detail="缺少 src_node / dst_node / rel")
    link_types = config.ontology_schema().get("link_types", {})
    if rel not in link_types:
        raise HTTPException(status_code=400,
                            detail=f"未知链接类型 {rel},可选:{'、'.join(link_types)}")
    with get_db() as db:
        _require_feature(db, p, "ontology", "本体图谱")
        for nid in (src, dst):
            if object_detail(db, nid) is None:
                raise HTTPException(status_code=404, detail=f"节点不存在: {nid}")
        dom_id = _node_domain(db, src) or _node_domain(db, dst)
        if dom_id:
            _check_domain(db, p, dom_id)
        cur = db.execute(
            "INSERT INTO edges(src_node, dst_node, rel, origin, domain_id, note) "
            "VALUES(?,?,?, 'manual',?,?)",
            (src, dst, rel, dom_id, body.get("note", "")))
        log_action(db, "add_link", f"{src} —{rel}→ {dst}", f"edg{cur.lastrowid}")
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/ontology/links/{edge_id}", dependencies=[Depends(_auth)])
def delete_link(edge_id: str, request: Request):
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "ontology", "本体图谱")
        if edge_id.startswith("edg") and edge_id[3:].isdigit():
            row = db.execute("SELECT src_node, rel, dst_node, domain_id FROM edges WHERE id=?",
                             (int(edge_id[3:]),)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="链接不存在")
            if row["domain_id"]:
                _check_domain(db, p, row["domain_id"])
            db.execute("DELETE FROM edges WHERE id=?", (int(edge_id[3:]),))
            log_action(db, "remove_link", f"{row['src_node']} —{row['rel']}→ {row['dst_node']}", edge_id)
        elif edge_id.startswith("rel") and edge_id[3:].isdigit():
            row = db.execute("SELECT src_id, rel, dst_id FROM relations WHERE id=?",
                             (int(edge_id[3:]),)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="链接不存在")
            _check_entity_owner(db, p, row["src_id"])
            db.execute("DELETE FROM relations WHERE id=?", (int(edge_id[3:]),))
            log_action(db, "remove_link", f"e{row['src_id']} —{row['rel']}→ e{row['dst_id']}",
                       edge_id + "(抽取链接,重新抽取会恢复)")
        else:
            raise HTTPException(status_code=400, detail="非法链接 id")
    return {"ok": True}


@router.post("/ontology/derive", dependencies=[Depends(_auth)])
def rederive(request: Request):
    """重算派生链接(归属/溯源/前置/变体/规则);租户仅重算本租户知识域。"""
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "ontology", "本体图谱")
        if p["super"]:
            counts = derive_all(db)
        else:
            counts = {did: derive_links(db, did)
                      for did in _tenant_domain_ids(db, p["tenant_id"])}
        log_action(db, "derive_links", json.dumps(counts, ensure_ascii=False))
    return {"ok": True, "counts": counts}


@router.get("/actions", dependencies=[Depends(_auth)])
def list_actions(request: Request, limit: int = 30):
    _require_super(request)
    with get_db() as db:
        rows = db.execute("SELECT * FROM actions_log ORDER BY id DESC LIMIT ?",
                          (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------- 配置文件编辑(热加载) ----------

def _config_path(name: str) -> Path:
    p = (config.CONFIG_DIR / name).resolve()
    if not str(p).startswith(str(config.CONFIG_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法路径")
    return p


@router.get("/config", dependencies=[Depends(_auth)])
def list_config_files(request: Request):
    _require_super(request)
    files = []
    for p in sorted(config.CONFIG_DIR.rglob("*")):
        if p.is_file() and p.suffix in (".yaml", ".md", ".json"):
            files.append(str(p.relative_to(config.CONFIG_DIR)).replace("\\", "/"))
    return files


@router.get("/config/{name:path}", dependencies=[Depends(_auth)])
def read_config_file(name: str, request: Request):
    _require_super(request)
    p = _config_path(name)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"name": name, "content": p.read_text(encoding="utf-8")}


@router.put("/config/{name:path}", dependencies=[Depends(_auth)])
async def write_config_file(name: str, request: Request):
    _require_super(request)
    body = await request.json()
    content = (body or {}).get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="缺少 content")
    p = _config_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "name": name}


# ---------- 模型与参数(llm.yaml 结构化读写) ----------

_LLM_EDITABLE = ("base_url", "api_key", "chat_model", "chat_models",
                 "embedding_model", "rerank_model",
                 "rerank_strategy", "rerank_url", "temperature", "max_tokens",
                 "request_timeout", "context_turns")


@router.get("/llm", dependencies=[Depends(_auth)])
def get_llm_config(request: Request):
    """读取生效的 LLM 配置(平台超管)。"""
    _require_super(request)
    cfg = config.llm_config()
    return {k: cfg.get(k) for k in _LLM_EDITABLE}


@router.put("/llm", dependencies=[Depends(_auth)])
async def put_llm_config(request: Request):
    """更新 llm.yaml(平台超管;白名单字段,热加载即时生效)。密钥仍只走环境变量。"""
    _require_super(request)
    body = await request.json() or {}
    patch = {k: body[k] for k in _LLM_EDITABLE if k in body}
    if not patch:
        raise HTTPException(status_code=400, detail="无可更新字段")
    p = _config_path("llm.yaml")
    existing = yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else {}
    existing = dict(existing or {})
    existing.update(patch)
    header = ("# LLM 参数(火山方舟 OpenAI 兼容接口)。密钥仅走环境变量,勿写入本文件。\n"
              "# context_turns:上下文轮次上限,0 或负数 = 不限制。\n")
    p.write_text(header + yaml.safe_dump(existing, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return {"ok": True}


# ---------- 会话与消息 ----------

@router.get("/sessions", dependencies=[Depends(_auth)])
def list_sessions(request: Request, limit: int = 50, date_from: str = "", date_to: str = ""):
    """会话列表,支持按更新时间范围筛选(date_from/date_to,YYYY-MM-DD)。租户仅见本租户会话。"""
    p = _principal(request)
    with get_db() as db0:
        _require_feature(db0, p, "sessions", "对话记录")
    sql = ("SELECT s.id, s.role, s.tenant_id, s.state_json, s.created_at, s.updated_at, "
           "(SELECT COUNT(*) FROM messages g WHERE g.session_id=s.id) AS msgs, "
           "(SELECT t.name FROM tenants t WHERE t.id=s.tenant_id) AS tenant_name, "
           "(SELECT qc.score FROM quality_checks qc WHERE qc.session_id=s.id "
           "  ORDER BY qc.id DESC LIMIT 1) AS quality_score "
           "FROM sessions s")
    args: list = []
    conds = []
    if not p["super"]:
        conds.append("s.tenant_id=?")
        args.append(p["tenant_id"])
    if date_from:
        conds.append("s.updated_at >= ?")
        args.append(date_from + " 00:00:00")
    if date_to:
        conds.append("s.updated_at <= ?")
        args.append(date_to + " 23:59:59")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY s.updated_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as db:
        rows = db.execute(sql, args).fetchall()
    return [{**dict(r), "state": json.loads(r["state_json"] or "{}")} for r in rows]


@router.get("/sessions/{sid}/messages", dependencies=[Depends(_auth)])
def session_messages(sid: str, request: Request):
    """消息明细:内容脱敏(手机号/邮箱/身份证号打码);租户仅可见本租户会话。"""
    from ..core.tenancy import mask_text
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "sessions", "对话记录")
        _check_session_owner(db, p, sid)
        rows = db.execute(
            "SELECT role, content, tool_calls_json, created_at FROM messages "
            "WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return [{**dict(r), "content": mask_text(r["content"]),
             "tool_calls": json.loads(r["tool_calls_json"] or "null")} for r in rows]


# ---------- 租户与平台看板(SaaS) ----------

@router.get("/tenants", dependencies=[Depends(_auth)])
def list_tenants(request: Request):
    """租户列表:套餐、用户数、会话数、当月用量(平台超管经营视图)。"""
    _require_super(request)
    with get_db() as db:
        rows = db.execute(
            "SELECT t.id, t.slug, t.name, t.created_at, "
            "  (SELECT plan_code FROM subscriptions s WHERE s.tenant_id=t.id) AS plan_code, "
            "  (SELECT COUNT(*) FROM users u WHERE u.tenant_id=t.id) AS users, "
            "  (SELECT COUNT(*) FROM sessions ss WHERE ss.tenant_id=t.id) AS sessions, "
            "  (SELECT COUNT(*) FROM messages m JOIN sessions ss ON ss.id=m.session_id "
            "    WHERE ss.tenant_id=t.id AND m.role='user') AS chats, "
            "  (SELECT IFNULL(SUM(chat_count),0) FROM usage_monthly um "
            "    WHERE um.tenant_id=t.id) AS total_usage "
            "FROM tenants t ORDER BY t.id").fetchall()
    return [dict(r) for r in rows]


@router.get("/dashboard", dependencies=[Depends(_auth)])
def dashboard(request: Request):
    """平台级看板:租户数/用户数/对话数总量 + 近14日会话趋势 + 租户对话排行。"""
    _require_super(request)
    from datetime import datetime, timedelta, timezone
    cst = timezone(timedelta(hours=8))
    today = datetime.now(cst).date()
    with get_db() as db:
        totals = db.execute(
            "SELECT (SELECT COUNT(*) FROM tenants) AS tenants, "
            "       (SELECT COUNT(*) FROM users) AS users, "
            "       (SELECT COUNT(*) FROM sessions) AS sessions, "
            "       (SELECT COUNT(*) FROM messages WHERE role='user') AS chats").fetchone()
        trend = []
        for i in range(13, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            n = db.execute("SELECT COUNT(*) FROM sessions WHERE substr(created_at,1,10)=?",
                           (d,)).fetchone()[0]
            trend.append({"date": d, "count": n})
        top = db.execute(
            "SELECT t.name, COUNT(m.id) AS chats FROM tenants t "
            "JOIN sessions ss ON ss.tenant_id=t.id "
            "JOIN messages m ON m.session_id=ss.id AND m.role='user' "
            "GROUP BY t.id ORDER BY chats DESC LIMIT 8").fetchall()
    return {"totals": dict(totals), "trend": trend,
            "top_tenants": [dict(r) for r in top]}


# ---------- 数据分析(智能体运营分析) ----------

_UNANSWERED_MARKS = ("无法确认", "不在我的参考", "不在本通道", "没有找到相关", "无法")


@router.get("/analytics", dependencies=[Depends(_auth)])
def get_analytics(request: Request, role: str = ""):
    """运营指标端点:超管看全量(可按智能体筛选),租户收敛到本租户会话。"""
    p = _principal(request)
    if p["super"]:
        return _analytics_data(role)
    with get_db() as db0:
        _require_feature(db0, p, "analytics", "运营分析")
    return _analytics_data("", tenant_id=p["tenant_id"])


def _analytics_data(role: str = "", tenant_id: int | None = None):
    """智能体运营指标:概览/各智能体/趋势/高频问题/未答问题/推荐分布。
    可按智能体筛选;tenant_id 指定时收敛到该租户会话。"""
    with get_db() as db:
        rc = [role] if role else []
        srf = "WHERE s.role=?" if role else ""
        mrf = "AND s.role=?" if role else ""
        if tenant_id:
            srf = "WHERE s.tenant_id=?" + (" AND s.role=?" if role else "")
            mrf = "AND s.tenant_id=?" + (" AND s.role=?" if role else "")
            rc = [tenant_id, role] if role else [tenant_id]
        total_sessions = db.execute(f"SELECT COUNT(*) FROM sessions s {srf}", rc).fetchone()[0]
        total_questions = db.execute(
            "SELECT COUNT(*) FROM messages m JOIN sessions s ON s.id=m.session_id "
            f"WHERE m.role='user' {mrf}", rc).fetchone()[0]
        by_agent = [dict(r) for r in db.execute(
            "SELECT role, COUNT(*) AS c FROM sessions GROUP BY role")]
        trend = [dict(r) for r in db.execute(
            f"SELECT substr(s.created_at,1,10) AS d, COUNT(*) AS c FROM sessions s {srf} "
            "GROUP BY d ORDER BY d DESC LIMIT 14", rc)]
        top_questions = [dict(r) for r in db.execute(
            "SELECT m.content AS q, COUNT(*) AS c FROM messages m "
            f"JOIN sessions s ON s.id=m.session_id WHERE m.role='user' {mrf} "
            "GROUP BY m.content ORDER BY c DESC LIMIT 10", rc)]
        # 未答/边界问题:回复含无法确认类措辞 → 回溯其前置用户提问
        unanswered, seen = [], set()
        rows = db.execute(
            "SELECT m.content, m.role FROM messages m JOIN sessions s ON s.id=m.session_id "
            f"{srf} ORDER BY m.id", rc).fetchall()
        prev_user = None
        for r in rows:
            if r["role"] == "user":
                prev_user = r["content"]
            elif r["role"] == "assistant" and any(
                    k in (r["content"] or "") for k in _UNANSWERED_MARKS):
                if prev_user and prev_user not in seen:
                    seen.add(prev_user)
                    unanswered.append({"q": prev_user})
        # 推荐班型分布:统计真实班型名(取自本体)在助手回复中的出现次数
        products = [r["name"] for r in db.execute(
            "SELECT DISTINCT name FROM entities WHERE type='product'")]
        assistant_text = "\n".join(r["content"] or "" for r in db.execute(
            f"SELECT m.content FROM messages m JOIN sessions s ON s.id=m.session_id "
            f"WHERE m.role='assistant' {mrf}", rc))
        recommend_dist = sorted(
            [{"name": p, "count": assistant_text.count(p)}
             for p in products if p and p in assistant_text],
            key=lambda x: -x["count"])
        # 各智能体平均质检分(质检功能上线后有值)
        quality = [dict(r) for r in db.execute(
            "SELECT agent_role AS role, ROUND(AVG(score)) AS avg_score, COUNT(*) AS c "
            "FROM quality_checks WHERE score IS NOT NULL GROUP BY agent_role")]
    return {
        "overview": {"total_sessions": total_sessions, "total_questions": total_questions},
        "by_agent": by_agent,
        "trend": list(reversed(trend)),
        "top_questions": top_questions,
        "unanswered": unanswered[:12],
        "recommend_dist": recommend_dist,
        "quality": quality,
    }


@router.get("/analytics/insight", dependencies=[Depends(_auth)])
def get_insight(request: Request, role: str = ""):
    _require_super(request)
    scope = role or "all"
    with get_db() as db:
        row = db.execute(
            "SELECT id, content, created_at FROM insights WHERE scope=? ORDER BY id DESC LIMIT 1",
            (scope,)).fetchone()
    return dict(row) if row else None


@router.post("/analytics/insight", dependencies=[Depends(_auth)])
async def gen_insight(request: Request):
    """把运营指标喂给 LLM 生成运营洞察并落库(平台超管)。"""
    _require_super(request)
    body = await request.json() or {}
    role = body.get("role", "")
    data = _analytics_data(role)
    prompt = config.get_prompt("insight") or "基于运营统计数据给出简洁可执行的运营洞察。"
    try:
        content = (llm.chat([
            {"role": "system", "content": prompt},
            {"role": "user",
             "content": "运营统计数据(JSON):\n" + json.dumps(data, ensure_ascii=False)[:6000]},
        ]).content or "").strip()
    except llm.LLMError:
        raise HTTPException(status_code=503, detail="模型服务暂时不可用,请稍后重试")
    scope = role or "all"
    with get_db() as db:
        cur = db.execute("INSERT INTO insights(scope, content) VALUES(?,?)", (scope, content))
        iid = cur.lastrowid
    return {"id": iid, "scope": scope, "content": content}


# ---------- 对话质检 ----------

@router.get("/quality", dependencies=[Depends(_auth)])
def list_quality(request: Request, session_id: str = "", role: str = ""):
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "sessions", "对话记录")
        sql = ("SELECT qc.id, qc.session_id, qc.agent_role, qc.score, qc.accuracy, "
               "qc.compliance, qc.experience, qc.issues_json, qc.comment, qc.created_at "
               "FROM quality_checks qc JOIN sessions s ON s.id=qc.session_id WHERE 1=1")
        args: list = []
        if not p["super"]:
            sql += " AND s.tenant_id=?"
            args.append(p["tenant_id"])
        if session_id:
            sql += " AND qc.session_id=?"
            args.append(session_id)
        if role:
            sql += " AND qc.agent_role=?"
            args.append(role)
        sql += " ORDER BY qc.id DESC LIMIT 200"
        rows = db.execute(sql, args).fetchall()
    return [{**dict(r), "issues": json.loads(r["issues_json"] or "[]")} for r in rows]


@router.post("/quality/{session_id}", dependencies=[Depends(_auth)])
def quality_one(session_id: str, request: Request):
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "sessions", "对话记录")
        _check_session_owner(db, p, session_id)
        return quality.check_session(db, session_id)


@router.post("/quality/batch", dependencies=[Depends(_auth)])
async def quality_batch(request: Request):
    """批量质检未质检的会话(默认最近 10 个有用户提问的会话);租户仅检本租户会话。"""
    p = _principal(request)
    body = await request.json() or {}
    limit = int(body.get("limit", 10))
    with get_db() as db:
        _require_feature(db, p, "sessions", "对话记录")
        sql = ("SELECT s.id FROM sessions s WHERE s.id NOT IN "
               "(SELECT session_id FROM quality_checks) "
               "AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id AND m.role='user') ")
        args: list = []
        if not p["super"]:
            sql += " AND s.tenant_id=?"
            args.append(p["tenant_id"])
        sql += " ORDER BY s.updated_at DESC LIMIT ?"
        args.append(limit)
        rows = db.execute(sql, args).fetchall()
        sids = [r["id"] for r in rows]
    results = []
    for sid in sids:
        with get_db() as db:
            results.append(quality.check_session(db, sid))
    return {"checked": len(results), "results": results}


# ---------- 报名意向 / 线索转化工单(留资转线索,非报名管理) ----------

_LEAD_STATUS = ("pending", "followed", "converted", "invalid")


@router.get("/leads", dependencies=[Depends(_auth)])
def list_leads(request: Request, status: str = "", role: str = ""):
    p = _principal(request)
    with get_db() as db:
        _require_feature(db, p, "leads", "线索转化")
        sql = ("SELECT l.* FROM leads l JOIN sessions s ON s.id=l.session_id WHERE 1=1")
        args: list = []
        if not p["super"]:
            sql += " AND s.tenant_id=?"
            args.append(p["tenant_id"])
        if status:
            sql += " AND l.status=?"
            args.append(status)
        if role:
            sql += " AND l.agent_role=?"
            args.append(role)
        sql += " ORDER BY l.id DESC LIMIT 200"
        rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@router.patch("/leads/{lead_id}", dependencies=[Depends(_auth)])
async def update_lead(lead_id: int, request: Request):
    p = _principal(request)
    with get_db() as db0:
        _require_feature(db0, p, "leads", "线索转化")
    body = await request.json() or {}
    sets: list[str] = []
    args: list = []
    if "status" in body:
        st = body["status"]
        if st not in _LEAD_STATUS:
            raise HTTPException(status_code=400, detail=f"无效状态,可选:{'/'.join(_LEAD_STATUS)}")
        sets.append("status=?")
        args.append(st)
        if st in ("followed", "converted"):
            sets.append("followed_at=datetime('now','localtime')")
    if "follow_note" in body:
        sets.append("follow_note=?")
        args.append(body["follow_note"])
    if not sets:
        raise HTTPException(status_code=400, detail="无可更新字段")
    args.append(lead_id)
    with get_db() as db:
        if not p["super"]:
            own = db.execute(
                "SELECT 1 FROM leads l JOIN sessions s ON s.id=l.session_id "
                "WHERE l.id=? AND s.tenant_id=?", (lead_id, p["tenant_id"])).fetchone()
            if not own:
                raise HTTPException(status_code=404, detail="工单不存在")
        cur = db.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id=?", args)
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="工单不存在")
        row = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    return dict(row)


# ---------- 渠道令牌(MCP 接入鉴权) ----------

def _gen_channel_token() -> str:
    import secrets
    return "ak_" + secrets.token_hex(24)


@router.get("/channels", dependencies=[Depends(_auth)])
def list_channels(request: Request):
    _require_super(request)
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, token, disabled, created_at, last_used_at "
            "FROM channel_tokens ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("/channels", dependencies=[Depends(_auth)])
async def create_channel(request: Request):
    _require_super(request)
    body = await request.json() or {}
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写渠道名称")
    with get_db() as db:
        for _ in range(5):
            token = _gen_channel_token()
            if not db.execute("SELECT 1 FROM channel_tokens WHERE token=?",
                              (token,)).fetchone():
                break
        cur = db.execute(
            "INSERT INTO channel_tokens(name, token) VALUES(?,?)", (name, token))
        row = db.execute("SELECT * FROM channel_tokens WHERE id=?",
                         (cur.lastrowid,)).fetchone()
    return dict(row)


@router.patch("/channels/{channel_id}", dependencies=[Depends(_auth)])
async def update_channel(channel_id: int, request: Request):
    _require_super(request)
    body = await request.json() or {}
    sets: list[str] = []
    args: list = []
    if "name" in body and (body["name"] or "").strip():
        sets.append("name=?")
        args.append(body["name"].strip())
    if "disabled" in body:
        sets.append("disabled=?")
        args.append(1 if body["disabled"] else 0)
    if not sets:
        raise HTTPException(status_code=400, detail="无可更新字段")
    args.append(channel_id)
    with get_db() as db:
        cur = db.execute(f"UPDATE channel_tokens SET {', '.join(sets)} WHERE id=?", args)
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="渠道不存在")
        row = db.execute("SELECT * FROM channel_tokens WHERE id=?",
                         (channel_id,)).fetchone()
    return dict(row)


@router.delete("/channels/{channel_id}", dependencies=[Depends(_auth)])
def delete_channel(channel_id: int, request: Request):
    _require_super(request)
    with get_db() as db:
        cur = db.execute("DELETE FROM channel_tokens WHERE id=?", (channel_id,))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="渠道不存在")
    return {"ok": True}


# ---------- 平台经营:套餐定价 / 订单管理(超管) ----------

@router.get("/plans", dependencies=[Depends(_auth)])
def admin_list_plans(request: Request):
    """套餐列表(含当前订阅租户数),供「套餐定价」页维护。"""
    _require_super(request)
    with get_db() as db:
        rows = db.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM subscriptions s "
            " WHERE s.plan_code=p.code AND s.status='active') AS active_subs "
            "FROM plans p ORDER BY p.price_monthly").fetchall()
    return [{**dict(r), "features": json.loads(r["features_json"] or "{}")} for r in rows]


@router.put("/plans/{code}", dependencies=[Depends(_auth)])
async def admin_update_plan(code: str, request: Request):
    """维护套餐展示名与价格(演示定价可在线调整)。"""
    _require_super(request)
    body = await request.json() or {}
    fields, args = [], []
    if "name" in body and (body["name"] or "").strip():
        fields.append("name=?")
        args.append(body["name"].strip())
    if "price_monthly" in body:
        try:
            price = float(body["price_monthly"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="价格需为数字")
        if price < 0:
            raise HTTPException(status_code=400, detail="价格不能为负")
        fields.append("price_monthly=?")
        args.append(price)
    if not fields:
        raise HTTPException(status_code=400, detail="无可更新字段")
    args.append(code)
    with get_db() as db:
        cur = db.execute(f"UPDATE plans SET {', '.join(fields)} WHERE code=?", args)
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="套餐不存在")
        log_action(db, "edit_plan", code, json.dumps(body, ensure_ascii=False)[:120])
    return {"ok": True}


@router.get("/orders", dependencies=[Depends(_auth)])
def admin_list_orders(request: Request, limit: int = 200):
    """全部订单(含租户名称),供「订单管理」页核对支付流水。"""
    _require_super(request)
    with get_db() as db:
        rows = db.execute(
            "SELECT o.*, t.name AS tenant_name, t.slug AS tenant_slug "
            "FROM payment_orders o JOIN tenants t ON t.id=o.tenant_id "
            "ORDER BY o.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
