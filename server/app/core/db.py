"""SQLite 单文件存储(data/app.db):ontology + 知识 + 会话。

- ontology:知识域 domains / 知识库 kbs / 文档 documents / entities / relations / rules
  (规则记录含推荐策略,引擎通用解释执行);实体与规则经 文档→知识库→知识域 链路归属。
- 知识:knowledge_chunks + FTS5(trigram,中文关键词召回)+ vec0(sqlite-vec 向量)。
- 会话:sessions / messages。

身份体系以「知识域」为唯一单位(无素材 A/B/C 概念);问答范围由智能体对接的知识域决定。
vec0 表在首次向量化拿到维度后延迟创建;sqlite-vec 不可用时向量召回降级为空,
主流程仍可由 FTS5 + ontology 支撑。
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager

from . import config

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS domains(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,            -- 知识域标识,如 domain-a
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS kbs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,            -- 知识库标识,如 kb-a
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  domain_id INTEGER REFERENCES domains(id),
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kb_id INTEGER NOT NULL REFERENCES kbs(id),
  filename TEXT NOT NULL,
  title TEXT,
  uploaded_at TEXT DEFAULT (datetime('now','localtime')),
  status TEXT DEFAULT 'ingested'        -- ingested / extracted / failed
);

CREATE TABLE IF NOT EXISTS knowledge_chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kb_id INTEGER NOT NULL REFERENCES kbs(id),
  doc_id INTEGER NOT NULL REFERENCES documents(id),
  doc_name TEXT NOT NULL,
  chapter TEXT,
  ord INTEGER,
  content TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  content, content='knowledge_chunks', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
  INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TABLE IF NOT EXISTS entities(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,                   -- product / period / location / person / fee_item ...
  name TEXT NOT NULL,
  attrs_json TEXT DEFAULT '{}',
  doc_id INTEGER NOT NULL REFERENCES documents(id),
  chapter TEXT,
  raw_excerpt TEXT,
  status TEXT DEFAULT 'extracted'       -- extracted / confirmed / edited
);

CREATE TABLE IF NOT EXISTS relations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src_id INTEGER NOT NULL REFERENCES entities(id),
  rel TEXT NOT NULL,
  dst_id INTEGER NOT NULL REFERENCES entities(id),
  doc_id INTEGER REFERENCES documents(id),
  chapter TEXT
);

-- 统一链接表:任意节点(实体 e/规则 r/文档 d/知识域 dom)间的类型化链接,
-- 抽取产生的实体间关系仍存 relations;派生链接与人工链接存此表,按知识域归属。
CREATE TABLE IF NOT EXISTS edges(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  src_node TEXT NOT NULL,              -- e12 / r3 / d2 / dom1
  dst_node TEXT NOT NULL,
  rel TEXT NOT NULL,
  origin TEXT DEFAULT 'derived',       -- derived / manual
  domain_id INTEGER REFERENCES domains(id),
  note TEXT
);

CREATE TABLE IF NOT EXISTS actions_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,                -- confirm_object / edit_object / add_link / ...
  target TEXT,
  detail TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                   -- early_bird / group_discount / stack_policy /
                                        -- fee_formula / refund / prerequisite / recommend ...
  scope_json TEXT DEFAULT '{}',
  params_json TEXT DEFAULT '{}',
  doc_id INTEGER NOT NULL REFERENCES documents(id),
  chapter TEXT,
  raw_excerpt TEXT,
  status TEXT DEFAULT 'extracted'
);

CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY,
  role TEXT DEFAULT 'platform',         -- student / teacher / platform
  state_json TEXT DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL,                   -- user / assistant / tool
  content TEXT,
  tool_calls_json TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ---------- 智能体运营(下游) ----------
-- LLM 运营洞察报告
CREATE TABLE IF NOT EXISTS insights(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT,                           -- 洞察范围(如 all / student / teacher / platform)
  content TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 对话质检评分
CREATE TABLE IF NOT EXISTS quality_checks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  agent_role TEXT,
  score INTEGER,                        -- 总分 0-100
  accuracy INTEGER,                     -- 准确性
  compliance INTEGER,                   -- 规范性(红线)
  experience INTEGER,                   -- 对话体验
  issues_json TEXT,                     -- 红线问题列表 JSON
  comment TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 报名意向 / 线索转化工单(留资转线索,非报名管理)
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  agent_role TEXT,
  name TEXT,
  phone TEXT,
  intent TEXT,                          -- 意向班型/诉求
  note TEXT,
  status TEXT DEFAULT 'pending',        -- pending / followed / converted / invalid
  follow_note TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  followed_at TEXT
);

-- 渠道令牌:分发给不同渠道(第三方 Agent/系统)接入 MCP 的 Bearer 令牌。
-- 一旦存在有效令牌,MCP 端点即要求携带有效令牌;无令牌时保持开放(向后兼容)。
CREATE TABLE IF NOT EXISTS channel_tokens(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,                   -- 渠道名称(如 WorkBuddy / 某合作系统)
  token TEXT UNIQUE NOT NULL,           -- ak_ 前缀令牌
  disabled INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  last_used_at TEXT
);
"""

vec_available = False


def _load_vec(db: sqlite3.Connection) -> None:
    global vec_available
    try:
        import sqlite_vec
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        vec_available = True
    except Exception as e:  # noqa: BLE001
        log.warning("sqlite-vec 不可用,向量召回降级为纯 FTS: %s", e)


@contextmanager
def get_db():
    config.ensure_dirs()
    db = sqlite3.connect(config.DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    _load_vec(db)
    db.executescript(SCHEMA)
    _ensure_domains_kbs(db)
    _migrate_drop_materials(db)
    try:
        from .ontology.engine import seed_recommend_rules
        seed_recommend_rules(db)
    except Exception as e:  # noqa: BLE001
        log.warning("种入推荐策略规则失败: %s", e)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


DEFAULT_DOMAINS = [
    ("domain-a", "学生课程知识域",
     "暑期AI素养夏令营:北京/上海线下班、线上直播班,营期、费用与物资"),
    ("domain-b", "教师培训知识域",
     "初高中教师AI素养培训体系:L1—L3 暑期集训班 / 周末研修班"),
    ("domain-c", "平台服务知识域",
     "OPC平台与会员服务(白皮书资料待补充)"),
]

DEFAULT_KBS = [
    ("kb-a", "domain-a", "学生夏令营知识库", "班型、营期、费用、大纲与物资准备"),
    ("kb-b", "domain-b", "教师培训知识库", "L1—L3 集训班/周末研修班与报名规则"),
    ("kb-c", "domain-c", "平台服务知识库", "平台与会员服务资料(待补充)"),
]


def _ensure_domains_kbs(db: sqlite3.Connection) -> None:
    """建默认知识域与知识库,回填 kb_id / domain_id(幂等)。"""
    for code, name, desc in DEFAULT_DOMAINS:
        db.execute("INSERT OR IGNORE INTO domains(code, name, description) VALUES(?,?,?)",
                   (code, name, desc))
    kb_cols = {r[1] for r in db.execute("PRAGMA table_info(kbs)")}
    if "domain_id" not in kb_cols:
        db.execute("ALTER TABLE kbs ADD COLUMN domain_id INTEGER REFERENCES domains(id)")
    for code, dom, name, desc in DEFAULT_KBS:
        db.execute("INSERT OR IGNORE INTO kbs(code, name, description) VALUES(?,?,?)",
                   (code, name, desc))
        db.execute("UPDATE kbs SET domain_id=(SELECT id FROM domains WHERE code=?) "
                   "WHERE code=? AND domain_id IS NULL", (dom, code))
    doc_cols = {r[1] for r in db.execute("PRAGMA table_info(documents)")}
    if "kb_id" not in doc_cols:
        db.execute("ALTER TABLE documents ADD COLUMN kb_id INTEGER REFERENCES kbs(id)")
    chunk_cols = {r[1] for r in db.execute("PRAGMA table_info(knowledge_chunks)")}
    if "kb_id" not in chunk_cols:
        db.execute("ALTER TABLE knowledge_chunks ADD COLUMN kb_id INTEGER REFERENCES kbs(id)")
    # 存量回填:知识库隶属知识域后,文档/知识块经知识库归属(仅在旧库尚有 materials 表时按素材回填)
    has_materials = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='materials'").fetchone()
    if has_materials:
        db.execute("UPDATE documents SET kb_id=(SELECT k.id FROM kbs k "
                   "JOIN materials m ON m.code=k.material_code WHERE m.id=documents.material_id) "
                   "WHERE kb_id IS NULL")
    db.execute("UPDATE knowledge_chunks SET kb_id=(SELECT d.kb_id FROM documents d "
               "WHERE d.id=knowledge_chunks.doc_id) WHERE kb_id IS NULL")


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _node_domain(db: sqlite3.Connection, node: str) -> int | None:
    """节点(e/r/d/dom)→ 所属知识域 id。"""
    for prefix, sql in (
        ("dom", "SELECT ? AS v"),
        ("e", "SELECT k.domain_id AS v FROM entities e JOIN documents d ON d.id=e.doc_id "
              "JOIN kbs k ON k.id=d.kb_id WHERE e.id=?"),
        ("r", "SELECT k.domain_id AS v FROM rules r JOIN documents d ON d.id=r.doc_id "
              "JOIN kbs k ON k.id=d.kb_id WHERE r.id=?"),
        ("d", "SELECT k.domain_id AS v FROM documents d JOIN kbs k ON k.id=d.kb_id WHERE d.id=?"),
    ):
        if node.startswith(prefix) and node[len(prefix):].isdigit():
            oid = int(node[len(prefix):])
            row = db.execute(sql, (oid,)).fetchone()
            return row["v"] if row and row["v"] is not None else None
    return None


def _migrate_drop_materials(db: sqlite3.Connection) -> None:
    """原地迁移:移除素材(A/B/C)身份体系,链接按知识域归属。仅在旧库存在 materials 表时执行。"""
    if not _has_table(db, "materials"):
        return  # 新库,无需迁移
    # edges 增加 domain_id 并按端点回填(派生边稍后由图谱重算,此处兼顾人工边)
    edge_cols = {r[1] for r in db.execute("PRAGMA table_info(edges)")}
    if "domain_id" not in edge_cols:
        db.execute("ALTER TABLE edges ADD COLUMN domain_id INTEGER REFERENCES domains(id)")
    for row in db.execute("SELECT id, src_node, dst_node FROM edges WHERE domain_id IS NULL"):
        dom = _node_domain(db, row["src_node"]) or _node_domain(db, row["dst_node"])
        if dom:
            db.execute("UPDATE edges SET domain_id=? WHERE id=?", (dom, row["id"]))
    # 删除素材列(先删子列再删 materials 表,外键始终可满足)
    for tbl, col in [("documents", "material_id"), ("knowledge_chunks", "material_id"),
                     ("entities", "material_id"), ("rules", "material_id"),
                     ("domains", "material_code"), ("kbs", "material_code"),
                     ("edges", "material_code")]:
        try:
            db.execute(f"ALTER TABLE {tbl} DROP COLUMN {col}")
        except sqlite3.OperationalError as e:
            log.warning("迁移:%s.%s 删除失败(%s),保留但不再使用", tbl, col, e)
    try:
        db.execute("DROP TABLE materials")
    except sqlite3.OperationalError as e:
        log.warning("迁移:materials 表删除失败: %s", e)
    log.info("迁移完成:已移除素材身份体系,ontology 改按知识域键控")


def list_domains(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute(
        "SELECT d.*, "
        "(SELECT COUNT(*) FROM kbs k WHERE k.domain_id=d.id) AS kbs, "
        "(SELECT COUNT(*) FROM entities e JOIN documents doc ON doc.id=e.doc_id "
        "  JOIN kbs k ON k.id=doc.kb_id WHERE k.domain_id=d.id) AS entities, "
        "(SELECT COUNT(*) FROM rules r JOIN documents doc ON doc.id=r.doc_id "
        "  JOIN kbs k ON k.id=doc.kb_id WHERE k.domain_id=d.id) AS rules "
        "FROM domains d ORDER BY d.id").fetchall()
    return [dict(r) for r in rows]


def list_kbs(db: sqlite3.Connection, domain_id: int | None = None) -> list[dict]:
    sql = ("SELECT k.*, dm.name AS domain_name, dm.code AS domain_code, "
           "(SELECT COUNT(*) FROM documents d WHERE d.kb_id=k.id) AS docs "
           "FROM kbs k LEFT JOIN domains dm ON dm.id=k.domain_id")
    args: list = []
    if domain_id:
        sql += " WHERE k.domain_id=?"
        args.append(domain_id)
    sql += " ORDER BY k.id"
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def kb_ids_by_codes(db: sqlite3.Connection, codes: list[str]) -> list[int]:
    if not codes:
        return []
    ph = ",".join("?" * len(codes))
    rows = db.execute(f"SELECT id FROM kbs WHERE code IN ({ph})", codes).fetchall()
    return [r["id"] for r in rows]


def domain_names_of_kbs(db: sqlite3.Connection, kb_ids: list[int]) -> list[str]:
    """知识库集合所属知识域的名称(用于工具范围描述)。"""
    if not kb_ids:
        return []
    ph = ",".join("?" * len(kb_ids))
    rows = db.execute(
        f"SELECT DISTINCT dm.name FROM kbs k JOIN domains dm ON dm.id=k.domain_id "
        f"WHERE k.id IN ({ph}) AND dm.name IS NOT NULL", kb_ids).fetchall()
    return [r[0] for r in rows]


def log_action(db: sqlite3.Connection, action: str, target: str = "",
               detail: str = "") -> None:
    db.execute("INSERT INTO actions_log(action, target, detail) VALUES(?,?,?)",
               (action, target, detail))


def ensure_vec_table(db: sqlite3.Connection, dim: int) -> None:
    """首次向量化后按实际维度建 vec0 表。"""
    db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(embedding float[{int(dim)}])")


def vec_search(db: sqlite3.Connection, embedding: list[float], k: int = 20) -> list[tuple[int, float]]:
    """KNN 向量召回,返回 [(chunk_id, distance)],距离越小越相关。"""
    if not vec_available:
        return []
    try:
        import sqlite_vec
        blob = sqlite_vec.serialize_float32(embedding)
        rows = db.execute(
            "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (blob, k),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
    except Exception as e:  # noqa: BLE001
        log.warning("vec 检索失败(表可能尚未创建): %s", e)
        return []


def fts_search(db: sqlite3.Connection, query: str, k: int = 20) -> list[tuple[int, float]]:
    """trigram 关键词召回,返回 [(chunk_id, bm25)],bm25 越小越相关。"""
    q = '"' + query.replace('"', '""') + '"'
    try:
        rows = db.execute(
            "SELECT rowid, bm25(chunks_fts) AS s FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY s LIMIT ?",
            (q, k),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
    except sqlite3.OperationalError as e:
        log.warning("fts 检索失败: %s", e)
        return []
