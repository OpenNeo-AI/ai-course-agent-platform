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


def _auth(request: Request) -> None:
    """双认:静态 portal token(兼容存量) 或 平台超管 JWT(SaaS 用户体系)。"""
    from ..core import auth as core_auth
    authh = request.headers.get("authorization", "")
    token = authh[7:].strip() if authh.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="未授权:令牌错误或缺失")
    if token == config.portal_token():
        return
    payload = core_auth.decode_token(token)
    if payload and payload.get("role") == "superadmin":
        return
    raise HTTPException(status_code=401, detail="未授权:令牌错误或缺失")


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
def get_agents():
    return config.agents_config()


@router.put("/agents", dependencies=[Depends(_auth)])
async def put_agents(request: Request):
    """按角色合并更新对接配置并重写 agents.yaml(热加载生效)。
    请求体:{"student": {"identity": "student", "domains": ["domain-a"]}, ...}"""
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
def get_domains():
    with get_db() as db:
        return list_domains(db)


@router.post("/domains", dependencies=[Depends(_auth)])
async def create_domain(request: Request):
    body = await request.json() or {}
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少知识域名称")
    import secrets
    with get_db() as db:
        code = f"domain-{secrets.token_hex(3)}"
        while db.execute("SELECT 1 FROM domains WHERE code=?", (code,)).fetchone():
            code = f"domain-{secrets.token_hex(3)}"
        cur = db.execute(
            "INSERT INTO domains(code, name, description) VALUES(?,?,?)",
            (code, name, body.get("description", "")))
    return {"ok": True, "id": cur.lastrowid, "code": code}


@router.put("/domains/{dom_id}", dependencies=[Depends(_auth)])
async def update_domain(dom_id: int, request: Request):
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
        cur = db.execute(f"UPDATE domains SET {', '.join(fields)} WHERE id=?", args)
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="知识域不存在")
    return {"ok": True}


@router.delete("/domains/{dom_id}", dependencies=[Depends(_auth)])
def delete_domain(dom_id: int):
    with get_db() as db:
        dom = db.execute("SELECT * FROM domains WHERE id=?", (dom_id,)).fetchone()
        if not dom:
            raise HTTPException(status_code=404, detail="知识域不存在")
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
def get_kbs(domain_id: int = 0):
    with get_db() as db:
        return list_kbs(db, domain_id or None)


@router.post("/kbs", dependencies=[Depends(_auth)])
async def create_kb(request: Request):
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
        if not dom:
            raise HTTPException(status_code=404, detail="目标知识域不存在")
        fields.append("domain_id=?")
        args.append(dom["id"])
    if not fields:
        raise HTTPException(status_code=400, detail="无可更新字段")
    args.append(kb_id)
    with get_db() as db:
        cur = db.execute(f"UPDATE kbs SET {', '.join(fields)} WHERE id=?", args)
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="知识库不存在")
    return {"ok": True}


@router.delete("/kbs/{kb_id}", dependencies=[Depends(_auth)])
def delete_kb(kb_id: int):
    with get_db() as db:
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
def list_documents(kb_id: int = 0):
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
        return [dict(r) for r in db.execute(sql, args).fetchall()]


@router.post("/documents", dependencies=[Depends(_auth)])
async def upload_document(file: UploadFile = File(...), kb_id: int = Form(...),
                          title: str = Form("")):
    """上传知识文档(.txt/.docx/.doc/.pdf)→ 解析 → 切块向量化 → ontology 抽取。
    归属知识库由 kb_id 指定(文档经 知识库→知识域 归属);同名文件自动重建。"""
    from ..core.ingest.parse import parse_upload
    with get_db() as db:
        kb = db.execute("SELECT * FROM kbs WHERE id=?", (kb_id,)).fetchone()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
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
def delete_document(doc_id: int):
    with get_db() as db:
        clear_document_knowledge(db, doc_id)
        db.execute("DELETE FROM relations WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM entities WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM rules WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return {"ok": True}


# ---------- 本体浏览与维护 ----------

@router.get("/entities", dependencies=[Depends(_auth)])
def list_entities(domain: str = "", type: str = "", status: str = ""):
    with get_db() as db:
        sql = ("SELECT e.id, dm.code AS domain_code, dm.name AS domain_name, "
               "e.type, e.name, e.attrs_json, e.chapter, e.status, e.raw_excerpt, d.filename "
               "FROM entities e JOIN documents d ON d.id=e.doc_id "
               "JOIN kbs k ON k.id=d.kb_id JOIN domains dm ON dm.id=k.domain_id WHERE 1=1")
        args: list = []
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
def list_rules(domain: str = "", kind: str = ""):
    with get_db() as db:
        sql = ("SELECT r.id, dm.code AS domain_code, dm.name AS domain_name, "
               "r.kind, r.scope_json, r.params_json, r.chapter, r.status, r.raw_excerpt, d.filename "
               "FROM rules r JOIN documents d ON d.id=r.doc_id "
               "JOIN kbs k ON k.id=d.kb_id JOIN domains dm ON dm.id=k.domain_id WHERE 1=1")
        args: list = []
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
def list_relations(domain: str = ""):
    sql = ("SELECT rel.id, dm.code AS domain_code, s.name AS src, rel.rel, t.name AS dst, rel.chapter "
           "FROM relations rel "
           "JOIN entities s ON s.id=rel.src_id JOIN entities t ON t.id=rel.dst_id "
           "JOIN documents d ON d.id=s.doc_id JOIN kbs k ON k.id=d.kb_id "
           "JOIN domains dm ON dm.id=k.domain_id WHERE 1=1")
    args: list = []
    if domain:
        sql += " AND dm.code=?"
        args.append(domain)
    with get_db() as db:
        rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@router.post("/entities/{eid}/confirm", dependencies=[Depends(_auth)])
def confirm_entity(eid: int):
    with get_db() as db:
        cur = db.execute("UPDATE entities SET status='confirmed' WHERE id=?", (eid,))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="实体不存在")
        row = db.execute("SELECT type, name FROM entities WHERE id=?", (eid,)).fetchone()
        log_action(db, "confirm_object", f"{row['type']}:{row['name']}", f"e{eid}")
    return {"ok": True}


@router.put("/entities/{eid}", dependencies=[Depends(_auth)])
async def update_entity(eid: int, request: Request):
    body = await request.json()
    attrs = (body or {}).get("attrs")
    name = (body or {}).get("name")
    if attrs is None:
        raise HTTPException(status_code=400, detail="缺少 attrs")
    with get_db() as db:
        row = db.execute("SELECT id FROM entities WHERE id=?", (eid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="实体不存在")
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
    body = await request.json()
    params = (body or {}).get("params")
    if params is None:
        raise HTTPException(status_code=400, detail="缺少 params")
    with get_db() as db:
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
def ontology_graph(domain: str = "", types: str = "", q: str = ""):
    with get_db() as db:
        return build_graph(db, domain or None,
                           [t for t in types.split(",") if t] if types else None,
                           q or None)


@router.get("/ontology/objects/{node_id}", dependencies=[Depends(_auth)])
def ontology_object(node_id: str):
    with get_db() as db:
        obj = object_detail(db, node_id)
    if not obj:
        raise HTTPException(status_code=404, detail="对象不存在")
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
    body = await request.json() or {}
    src, dst, rel = body.get("src_node", ""), body.get("dst_node", ""), body.get("rel", "")
    if not (src and dst and rel):
        raise HTTPException(status_code=400, detail="缺少 src_node / dst_node / rel")
    link_types = config.ontology_schema().get("link_types", {})
    if rel not in link_types:
        raise HTTPException(status_code=400,
                            detail=f"未知链接类型 {rel},可选:{'、'.join(link_types)}")
    with get_db() as db:
        for nid in (src, dst):
            if object_detail(db, nid) is None:
                raise HTTPException(status_code=404, detail=f"节点不存在: {nid}")
        dom_id = _node_domain(db, src) or _node_domain(db, dst)
        cur = db.execute(
            "INSERT INTO edges(src_node, dst_node, rel, origin, domain_id, note) "
            "VALUES(?,?,?, 'manual',?,?)",
            (src, dst, rel, dom_id, body.get("note", "")))
        log_action(db, "add_link", f"{src} —{rel}→ {dst}", f"edg{cur.lastrowid}")
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/ontology/links/{edge_id}", dependencies=[Depends(_auth)])
def delete_link(edge_id: str):
    with get_db() as db:
        if edge_id.startswith("edg") and edge_id[3:].isdigit():
            row = db.execute("SELECT src_node, rel, dst_node FROM edges WHERE id=?",
                             (int(edge_id[3:]),)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="链接不存在")
            db.execute("DELETE FROM edges WHERE id=?", (int(edge_id[3:]),))
            log_action(db, "remove_link", f"{row['src_node']} —{row['rel']}→ {row['dst_node']}", edge_id)
        elif edge_id.startswith("rel") and edge_id[3:].isdigit():
            row = db.execute("SELECT src_id, rel, dst_id FROM relations WHERE id=?",
                             (int(edge_id[3:]),)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="链接不存在")
            db.execute("DELETE FROM relations WHERE id=?", (int(edge_id[3:]),))
            log_action(db, "remove_link", f"e{row['src_id']} —{row['rel']}→ e{row['dst_id']}",
                       edge_id + "(抽取链接,重新抽取会恢复)")
        else:
            raise HTTPException(status_code=400, detail="非法链接 id")
    return {"ok": True}


@router.post("/ontology/derive", dependencies=[Depends(_auth)])
def rederive():
    """重算全部派生链接(归属/溯源/前置/变体/规则)。"""
    with get_db() as db:
        counts = derive_all(db)
        log_action(db, "derive_links", json.dumps(counts, ensure_ascii=False))
    return {"ok": True, "counts": counts}


@router.get("/actions", dependencies=[Depends(_auth)])
def list_actions(limit: int = 30):
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
def list_config_files():
    files = []
    for p in sorted(config.CONFIG_DIR.rglob("*")):
        if p.is_file() and p.suffix in (".yaml", ".md", ".json"):
            files.append(str(p.relative_to(config.CONFIG_DIR)).replace("\\", "/"))
    return files


@router.get("/config/{name:path}", dependencies=[Depends(_auth)])
def read_config_file(name: str):
    p = _config_path(name)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"name": name, "content": p.read_text(encoding="utf-8")}


@router.put("/config/{name:path}", dependencies=[Depends(_auth)])
async def write_config_file(name: str, request: Request):
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
def get_llm_config():
    """读取生效的 LLM 配置(默认值 + 环境变量 + llm.yaml 合并后,仅返回可编辑字段)。"""
    cfg = config.llm_config()
    return {k: cfg.get(k) for k in _LLM_EDITABLE}


@router.put("/llm", dependencies=[Depends(_auth)])
async def put_llm_config(request: Request):
    """更新 llm.yaml(仅白名单字段;热加载即时生效)。密钥仍只走环境变量。"""
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
def list_sessions(limit: int = 50):
    with get_db() as db:
        rows = db.execute(
            "SELECT s.id, s.role, s.state_json, s.created_at, s.updated_at, "
            "(SELECT COUNT(*) FROM messages g WHERE g.session_id=s.id) AS msgs, "
            "(SELECT qc.score FROM quality_checks qc WHERE qc.session_id=s.id "
            "  ORDER BY qc.id DESC LIMIT 1) AS quality_score "
            "FROM sessions s ORDER BY s.updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "state": json.loads(r["state_json"] or "{}")} for r in rows]


@router.get("/sessions/{sid}/messages", dependencies=[Depends(_auth)])
def session_messages(sid: str):
    with get_db() as db:
        rows = db.execute(
            "SELECT role, content, tool_calls_json, created_at FROM messages "
            "WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return [{**dict(r),
             "tool_calls": json.loads(r["tool_calls_json"] or "null")} for r in rows]


# ---------- 数据分析(智能体运营分析) ----------

_UNANSWERED_MARKS = ("无法确认", "不在我的参考", "不在本通道", "没有找到相关", "无法")


@router.get("/analytics", dependencies=[Depends(_auth)])
def get_analytics(role: str = ""):
    """智能体运营指标:概览/各智能体/趋势/高频问题/未答问题/推荐分布。可按智能体筛选。"""
    with get_db() as db:
        rc = [role] if role else []
        srf = "WHERE s.role=?" if role else ""
        mrf = "AND s.role=?" if role else ""
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
def get_insight(role: str = ""):
    scope = role or "all"
    with get_db() as db:
        row = db.execute(
            "SELECT id, content, created_at FROM insights WHERE scope=? ORDER BY id DESC LIMIT 1",
            (scope,)).fetchone()
    return dict(row) if row else None


@router.post("/analytics/insight", dependencies=[Depends(_auth)])
async def gen_insight(request: Request):
    """把运营指标喂给 LLM 生成运营洞察并落库。"""
    body = await request.json() or {}
    role = body.get("role", "")
    data = get_analytics(role)
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
def list_quality(session_id: str = "", role: str = ""):
    with get_db() as db:
        sql = ("SELECT id, session_id, agent_role, score, accuracy, compliance, experience, "
               "issues_json, comment, created_at FROM quality_checks WHERE 1=1")
        args: list = []
        if session_id:
            sql += " AND session_id=?"
            args.append(session_id)
        if role:
            sql += " AND agent_role=?"
            args.append(role)
        sql += " ORDER BY id DESC LIMIT 200"
        rows = db.execute(sql, args).fetchall()
    return [{**dict(r), "issues": json.loads(r["issues_json"] or "[]")} for r in rows]


@router.post("/quality/{session_id}", dependencies=[Depends(_auth)])
def quality_one(session_id: str):
    with get_db() as db:
        return quality.check_session(db, session_id)


@router.post("/quality/batch", dependencies=[Depends(_auth)])
async def quality_batch(request: Request):
    """批量质检未质检的会话(默认最近 10 个有用户提问的会话)。"""
    body = await request.json() or {}
    limit = int(body.get("limit", 10))
    with get_db() as db:
        rows = db.execute(
            "SELECT s.id FROM sessions s WHERE s.id NOT IN "
            "(SELECT session_id FROM quality_checks) "
            "AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id AND m.role='user') "
            "ORDER BY s.updated_at DESC LIMIT ?", (limit,)).fetchall()
        sids = [r["id"] for r in rows]
    results = []
    for sid in sids:
        with get_db() as db:
            results.append(quality.check_session(db, sid))
    return {"checked": len(results), "results": results}


# ---------- 报名意向 / 线索转化工单(留资转线索,非报名管理) ----------

_LEAD_STATUS = ("pending", "followed", "converted", "invalid")


@router.get("/leads", dependencies=[Depends(_auth)])
def list_leads(status: str = "", role: str = ""):
    with get_db() as db:
        sql = "SELECT * FROM leads WHERE 1=1"
        args: list = []
        if status:
            sql += " AND status=?"
            args.append(status)
        if role:
            sql += " AND agent_role=?"
            args.append(role)
        sql += " ORDER BY id DESC LIMIT 200"
        rows = db.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@router.patch("/leads/{lead_id}", dependencies=[Depends(_auth)])
async def update_lead(lead_id: int, request: Request):
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
def list_channels():
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, token, disabled, created_at, last_used_at "
            "FROM channel_tokens ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("/channels", dependencies=[Depends(_auth)])
async def create_channel(request: Request):
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
def delete_channel(channel_id: int):
    with get_db() as db:
        cur = db.execute("DELETE FROM channel_tokens WHERE id=?", (channel_id,))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="渠道不存在")
    return {"ok": True}
