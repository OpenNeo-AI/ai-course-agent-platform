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

import json
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

-- ---------- SaaS:多租户 / 套餐订阅 / 用量 / 支付(A级测试单) ----------
-- 租户:教育机构客户。官方演示知识域(domain-a/b/c)tenant_id 为 NULL,不属于任何租户。
CREATE TABLE IF NOT EXISTS tenants(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,            -- 对话入口标识 /b/<slug>
  name TEXT NOT NULL,                   -- 机构名称
  bot_config_json TEXT DEFAULT '{}',    -- 智能体设置:{welcome_text, lead_capture, model}
  service_purpose TEXT DEFAULT '',      -- 机构统一服务宗旨(注入所有智能体系统提示词)
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 用户:租户管理员(tenant_id 归属)与平台超管(tenant_id=NULL)。
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER REFERENCES tenants(id),
  username TEXT UNIQUE NOT NULL,
  email TEXT DEFAULT '',
  password_hash TEXT NOT NULL,          -- pbkdf2_sha256$salt$hash
  role TEXT DEFAULT 'admin',            -- superadmin(平台) / admin(租户管理员) / member
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 套餐定义:free 每月限额对话;pro 无限对话并解锁知识库管理与数据看板。
CREATE TABLE IF NOT EXISTS plans(
  code TEXT PRIMARY KEY,                -- free / standard / flagship
  name TEXT NOT NULL,
  price_monthly REAL DEFAULT 0,         -- 演示价格
  chat_limit_month INTEGER DEFAULT -1,  -- -1 表示无限
  features_json TEXT DEFAULT '{}',
  agent_limit INTEGER DEFAULT 1         -- 智能体数量上限,-1 不限
);

-- 订阅:每租户一条,记录当前套餐。
CREATE TABLE IF NOT EXISTS subscriptions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER UNIQUE NOT NULL REFERENCES tenants(id),
  plan_code TEXT NOT NULL REFERENCES plans(code),
  status TEXT DEFAULT 'active',
  current_period_end TEXT,
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 月度用量:免费版按自然月计数对话次数。
CREATE TABLE IF NOT EXISTS usage_monthly(
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  year_month TEXT NOT NULL,             -- YYYY-MM(北京时间)
  chat_count INTEGER DEFAULT 0,
  PRIMARY KEY(tenant_id, year_month)
);

-- 支付订单:mock(演示) / wechat(Native 扫码) / alipay(电脑网站支付)。
CREATE TABLE IF NOT EXISTS payment_orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  plan_code TEXT NOT NULL,
  channel TEXT DEFAULT 'mock',          -- mock / wechat / alipay
  amount REAL DEFAULT 0,
  status TEXT DEFAULT 'pending',        -- pending / paid / failed
  out_trade_no TEXT UNIQUE,             -- 渠道商户单号
  trade_no TEXT DEFAULT '',              -- 渠道交易号(回调/查询回填)
  created_at TEXT DEFAULT (datetime('now','localtime')),
  paid_at TEXT
);

-- 手机验证码(参照 OpenNeo verification_codes):发送即覆盖,5 分钟有效。
CREATE TABLE IF NOT EXISTS sms_codes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phone TEXT NOT NULL,
  code TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 租户智能体:每租户可建多个,各自独立配置与前台链接(/b/<slug>)。
CREATE TABLE IF NOT EXISTS tenant_agents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  slug TEXT UNIQUE NOT NULL,            -- 前台对话入口 /b/<slug>
  name TEXT NOT NULL,
  config_json TEXT DEFAULT '{}',        -- {model, lead_capture, quality_check, domains, prompt_text, welcome_text}
  created_at TEXT DEFAULT (datetime('now','localtime'))
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
    _migrate_saas(db)
    _seed_saas(db)
    _ensure_default_agents(db)
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


# ---------- SaaS 迁移与种子(幂等) ----------

# 套餐定义:免费版(注册即开通,仅智能体设置) / 标准版(知识域智能体) / 旗舰版(全功能)
# 元组:(code, name, price, chat_limit, features_json, agent_limit)  agent_limit -1=不限
# features_json 中 highlights 为套餐卡片逐行亮点(一行一点,前后端共用)
SAAS_PLANS = [
    ("free", "免费版", 0.0, -1,
     '{"agent_settings": true, "agent_caps": false, "domains": false, "rag_manage": false,'
     ' "ontology": false, "sessions": false, "leads": false, "analytics": false, "skills": false,'
     ' "desc": "快速体验智能体设置与 AI 对话",'
     ' "highlights": ["智能体设置:欢迎语 / 系统提示词", "1 个智能体 · 独立前台链接",'
     ' "无限 AI 对话体验", "知识域对接 / 业务功能需升级解锁"]}', 1),
    ("standard", "标准版", 59.0, -1,
     '{"agent_settings": true, "agent_caps": false, "domains": true, "rag_manage": true,'
     ' "ontology": true, "sessions": false, "leads": false, "analytics": false, "skills": true,'
     ' "desc": "把机构课程资料变成专属 AI 顾问",'
     ' "highlights": ["最多 3 个智能体 · 独立前台链接", "知识域与课程资料管理(RAG 带引用问答)",'
     ' "本体知识维护", "Agent Skill:课程详情 / 班型推荐"]}', 3),
    ("flagship", "旗舰版", 199.0, -1,
     '{"agent_settings": true, "agent_caps": true, "domains": true, "rag_manage": true,'
     ' "ontology": true, "sessions": true, "leads": true, "analytics": true, "skills": true,'
     ' "desc": "覆盖咨询获客到转化的完整经营闭环",'
     ' "highlights": ["智能体数量不限 · 独立前台链接", "能力开关:留资转线索 / 对话质检",'
     ' "对话记录(脱敏) · 线索跟进", "运营分析 · 用量统计看板"]}', -1),
]

STARTER_DOC_TITLE = "平台使用指南"
STARTER_DOC_TEXT = """第一章 平台简介
本机构已接入「AI教育顾问SaaS平台」。我是本机构的AI课程顾问,可以基于机构上传的课程资料为你解答课程安排、费用、师资等问题,并在资料范围内推荐适合的班型。
第二章 我能做什么
1. 课程问答:基于机构知识库回答课程大纲、时间、地点、费用等问题,回答附带资料来源。
2. 班型推荐:告诉我你所在的城市与时间偏好,我会在机构课程范围内推荐适合的班型并说明理由。
3. 边界说明:资料范围内的问题据实作答;超出资料范围的问题,我会明确告知「该问题不在我的知识范围内」,不编造信息。
第三章 温馨提示
课程余位与报名结果以机构人工确认为准,我不提供实时余位查询。如需人工服务,请联系本机构课程顾问。
"""


def _migrate_saas(db: sqlite3.Connection) -> None:
    """存量表增加 tenant_id(NULL 兼容:官方会话/官方知识域不属于任何租户);
    users 增加 phone(手机验证码注册/登录)。"""
    for tbl in ("sessions", "domains"):
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({tbl})")}
        if "tenant_id" not in cols:
            db.execute(f"ALTER TABLE {tbl} ADD COLUMN tenant_id INTEGER REFERENCES tenants(id)")
    tenant_cols = {r[1] for r in db.execute("PRAGMA table_info(tenants)")}
    if "bot_config_json" not in tenant_cols:
        db.execute("ALTER TABLE tenants ADD COLUMN bot_config_json TEXT DEFAULT '{}'")
    if "service_purpose" not in tenant_cols:
        db.execute("ALTER TABLE tenants ADD COLUMN service_purpose TEXT DEFAULT ''")
    user_cols = {r[1] for r in db.execute("PRAGMA table_info(users)")}
    if "phone" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    order_cols = {r[1] for r in db.execute("PRAGMA table_info(payment_orders)")}
    if "out_trade_no" not in order_cols:
        db.execute("ALTER TABLE payment_orders ADD COLUMN out_trade_no TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_out_trade_no "
               "ON payment_orders(out_trade_no)")
    if "trade_no" not in order_cols:
        db.execute("ALTER TABLE payment_orders ADD COLUMN trade_no TEXT DEFAULT ''")
    sess_cols = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
    if "agent_id" not in sess_cols:
        db.execute("ALTER TABLE sessions ADD COLUMN agent_id INTEGER REFERENCES tenant_agents(id)")


def _ensure_default_agents(db: sqlite3.Connection) -> None:
    """为尚无智能体的租户创建默认智能体(配置取自旧 tenants.bot_config_json)。"""
    import secrets as _secrets
    rows = db.execute(
        "SELECT t.id, t.name, t.bot_config_json FROM tenants t "
        "WHERE t.id NOT IN (SELECT DISTINCT tenant_id FROM tenant_agents)").fetchall()
    for t in rows:
        slug = "a-" + _secrets.token_hex(3)
        while db.execute("SELECT 1 FROM tenant_agents WHERE slug=?", (slug,)).fetchone():
            slug = "a-" + _secrets.token_hex(3)
        db.execute("INSERT INTO tenant_agents(tenant_id, slug, name, config_json) "
                   "VALUES(?,?,?,?)",
                   (t["id"], slug, "AI 课程顾问", t["bot_config_json"] or "{}"))


def _migrate_saas_plans(db: sqlite3.Connection) -> None:
    """套餐体系重构迁移:旧 free/pro 订阅映射到 standard/flagship,清理旧套餐定义;
    并按 SAAS_PLANS 校正功能位(标准版纳入本体知识)。"""
    # 历史一次性迁移(仅极旧库存有 pro 套餐):pro → flagship。
    # 新版 free 为合法套餐(注册即开通),不得在此清理。
    codes = {r["code"] for r in db.execute("SELECT code FROM plans")}
    if "pro" in codes:
        db.execute("UPDATE subscriptions SET plan_code='flagship' WHERE plan_code='pro'")
        db.execute("DELETE FROM plans WHERE code='pro'")
    # 功能位校正:存量套餐行 features_json 缺少新增功能位键(如 agent_caps/domains)
    # 时按 SAAS_PLANS 最新定义重写(仅 features,不覆盖超管对名称/价格的在线编辑)
    plan_features = {code: features for code, _n, _p, _l, features, _a in SAAS_PLANS}
    for code, features in plan_features.items():
        row = db.execute("SELECT features_json FROM plans WHERE code=?", (code,)).fetchone()
        if not row:
            continue
        try:
            cur = json.loads(row["features_json"] or "{}")
        except (ValueError, TypeError):
            cur = {}
        cur_keys = set(cur.keys())
        new = json.loads(features)
        # 缺新增功能位键,或 desc/highlights 与最新定义不一致 → 按 SAAS_PLANS 重写
        # (名称/价格不覆盖,保留超管在线编辑;desc/highlights 为产品文案随代码发布)
        if (not set(new.keys()) <= cur_keys
                or cur.get("desc") != new.get("desc")
                or cur.get("highlights") != new.get("highlights")):
            db.execute("UPDATE plans SET features_json=? WHERE code=?", (features, code))
    # agent_limit 列与取值校正(-1 不限)
    plan_cols = {r[1] for r in db.execute("PRAGMA table_info(plans)")}
    if "agent_limit" not in plan_cols:
        db.execute("ALTER TABLE plans ADD COLUMN agent_limit INTEGER DEFAULT 1")
    for code, _n, _p, _l, _f, agent_limit in SAAS_PLANS:
        db.execute("UPDATE plans SET agent_limit=? WHERE code=?", (agent_limit, code))
    # status 列补充(旧行默认 active;新注册显式 unpaid)
    sub_cols = {r[1] for r in db.execute("PRAGMA table_info(subscriptions)")}
    if "status" not in sub_cols:
        db.execute("ALTER TABLE subscriptions ADD COLUMN status TEXT DEFAULT 'active'")


def _seed_saas(db: sqlite3.Connection) -> None:
    """种入套餐、平台超管与官方演示租户(幂等)。
    用户种子仅在 users 表为空时执行——pbkdf2 哈希较慢,不得在每次连接时重复计算。"""
    # 先迁移清理旧 free/pro 套餐,再按 SAAS_PLANS 种子重建(避免旧 free 与新 free 冲突)
    _migrate_saas_plans(db)
    for code, name, price, limit, features, agent_limit in SAAS_PLANS:
        # INSERT OR IGNORE:不覆盖超管在「套餐定价」中的在线编辑
        db.execute("INSERT OR IGNORE INTO plans(code, name, price_monthly, chat_limit_month, "
                   "features_json, agent_limit) VALUES(?,?,?,?,?,?)",
                   (code, name, price, limit, features, agent_limit))
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    from . import auth
    # 平台超管:与 portal 登录账户保持一致(accounts.yaml 默认 demo/demo1234)
    accounts = config.portal_accounts() or [{"username": "demo", "password": "demo1234"}]
    acc = accounts[0]
    db.execute("INSERT OR IGNORE INTO users(username, password_hash, role) VALUES(?,?,?)",
               (acc["username"], auth.hash_password(acc["password"]), "superadmin"))
    # 官方演示租户(旗舰版已开通,供评审直接体验全功能工作台)
    db.execute("INSERT OR IGNORE INTO tenants(slug, name) VALUES(?,?)",
               ("demo", "演示教育机构(官方)"))
    row = db.execute("SELECT id FROM tenants WHERE slug='demo'").fetchone()
    demo_id = row["id"]
    db.execute("INSERT OR IGNORE INTO users(tenant_id, username, password_hash, role) "
               "VALUES(?,?,?,?)",
               (demo_id, "demo-org", auth.hash_password("demo1234"), "admin"))
    db.execute("INSERT OR IGNORE INTO subscriptions(tenant_id, plan_code, status) "
               "VALUES(?,?, 'active')", (demo_id, "flagship"))
    db.execute("INSERT OR IGNORE INTO domains(code, name, description, tenant_id) VALUES(?,?,?,?)",
               ("dom-tdemo0", "演示课程知识域", "演示租户的课程知识(官方)", demo_id))
    dom_id = db.execute("SELECT id FROM domains WHERE code='dom-tdemo0'").fetchone()["id"]
    db.execute("INSERT OR IGNORE INTO kbs(code, name, description, domain_id) VALUES(?,?,?,?)",
               ("kb-tdemo0", "演示课程知识库", "演示租户知识库", dom_id))


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
