"""路径与配置中心。

所有运行时数据落在 server/data/:
  config/llm.yaml   LLM 参数(模型/温度/rerank 策略……),portal 可改写
  config/prompts/   角色提示词(*.md)
  config/schemas/   ontology 抽取 JSON Schema(*.json)
  uploads/          知识文档原件
  reports/          LLM 分析报告
  app.db            SQLite 单文件(ontology + 知识 + 会话)

配置按 mtime 热加载,修改后下一次读取即生效,无需重启。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]          # server/
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = DATA_DIR / "config"
PROMPT_DIR = CONFIG_DIR / "prompts"
SCHEMA_DIR = CONFIG_DIR / "schemas"
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "app.db"

DEFAULT_LLM_CONFIG = {
    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    "api_key": "",                       # 对话 API 密钥;空则回退环境变量 VOLCANO_API_KEY/ARK_API_KEY
    "chat_model": "doubao-seed-1-6-250615",
    "chat_models": ["doubao-seed-1-6-250615"],   # 可选对话模型清单(供各智能体切换)
    "embedding_model": "doubao-embedding-seed-250615",
    "rerank_model": "doubao-seed-rerank-250615",
    "rerank_strategy": "llm",      # llm | endpoint(endpoint 需配 rerank_url)
    "rerank_url": "",
    "temperature": 0.3,
    "max_tokens": 2048,
    "request_timeout": 60,
    "context_turns": 24,   # 上下文轮次上限(注入历史消息数);0 或负数 = 不限制
}

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

# ---------- 环境变量(仓库根 .env + 进程环境,进程环境优先) ----------

_env_file_cache: dict[str, str] | None = None


def _load_env_file() -> dict[str, str]:
    global _env_file_cache
    if _env_file_cache is not None:
        return _env_file_cache
    env: dict[str, str] = {}
    p = BASE_DIR.parent / ".env"                        # 仓库根目录 .env
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    _env_file_cache = env
    return env


def env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v not in (None, ""):
        return v
    v = _load_env_file().get(key)
    if v not in (None, ""):
        return v
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(env(key) or "")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, PROMPT_DIR, SCHEMA_DIR, UPLOAD_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    llm_yaml = CONFIG_DIR / "llm.yaml"
    if not llm_yaml.exists():
        llm_yaml.write_text(
            "# LLM 参数(OpenAI 兼容接口)。可由 portal 编辑;密钥仅走仓库根 .env/环境变量:\n"
            "#   对话:VOLCANO_API_KEY / VOLCANO_BASE_URL / VOLCANO_MODEL(覆盖本文件)\n"
            "#   向量:ARK_EMBED_KEY / ARK_EMBED_URL / ARK_EMBED_MODEL(缺省回退对话配置)\n"
            + yaml.safe_dump(DEFAULT_LLM_CONFIG, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def _cached(path: Path, loader):
    with _lock:
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return None
        hit = _cache.get(str(path))
        if hit and hit[0] == mtime:
            return hit[1]
        data = loader(path)
        _cache[str(path)] = (mtime, data)
        return data


def llm_config() -> dict:
    """LLM 配置,优先级:环境变量(.env) > data/config/llm.yaml > 默认值。
    模型/地址以环境变量为准(线上经 .env 指定可用的推理端点),保证模型服务连通。"""
    ensure_dirs()
    data = _cached(CONFIG_DIR / "llm.yaml",
                   lambda p: yaml.safe_load(p.read_text(encoding="utf-8")) or {}) or {}
    merged = dict(DEFAULT_LLM_CONFIG)
    merged.update({k: v for k, v in data.items() if v is not None})
    # 环境变量覆盖(chat 与 embed 可为两套独立服务)
    if v := env("VOLCANO_BASE_URL"):
        merged["base_url"] = v
    if v := env("VOLCANO_MODEL"):
        merged["chat_model"] = v
    merged["embed_base_url"] = env("ARK_EMBED_URL") or merged["base_url"]
    merged["embed_model"] = env("ARK_EMBED_MODEL") or merged["embedding_model"]
    return merged


def chat_credentials() -> tuple[str, str]:
    """(api_key, base_url)。密钥仅从环境变量/.env 读取。"""
    cfg = llm_config()
    key = env("VOLCANO_API_KEY") or env("ARK_API_KEY") or ""
    return key, cfg["base_url"]


def embed_credentials() -> tuple[str, str, str]:
    """(api_key, base_url, model)。embedding 可为独立服务,缺省回退对话配置。
    若配置的 URL 已含 /embeddings 路径,自动剥离(SDK 会自行追加)。"""
    cfg = llm_config()
    key = env("ARK_EMBED_KEY") or env("VOLCANO_API_KEY") or env("ARK_API_KEY") or ""
    base_url = cfg["embed_base_url"]
    suffix = "/embeddings"
    if base_url.rstrip("/").endswith(suffix):
        base_url = base_url.rstrip("/")[:-len(suffix)]
    return key, base_url, cfg["embed_model"]


# ---------- 运行参数(.env 优先,均有默认) ----------

def portal_token() -> str:
    """portal 登录令牌:.env 的 PORTAL_TOKEN 优先;否则自动生成并落盘(仅服务端可读)。"""
    if t := env("PORTAL_TOKEN"):
        return t
    ensure_dirs()
    f = CONFIG_DIR / "portal_token.txt"
    if not f.exists():
        import secrets
        f.write_text(secrets.token_urlsafe(16), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


def portal_accounts() -> list[dict]:
    """工作台登录账户。优先级:环境变量 PORTAL_USERNAME/PORTAL_PASSWORD > accounts.yaml > 默认演示账户。"""
    if (u := env("PORTAL_USERNAME")) and (pw := env("PORTAL_PASSWORD")):
        return [{"username": u, "password": pw}]
    ensure_dirs()
    f = CONFIG_DIR / "accounts.yaml"
    if f.exists():
        data = _cached(f, lambda p: yaml.safe_load(p.read_text(encoding="utf-8")) or {}) or {}
        accs = data.get("accounts")
        if accs:
            return [{"username": str(a.get("username", "")), "password": str(a.get("password", ""))}
                    for a in accs if a.get("username")]
    return [{"username": "demo", "password": "demo1234"}]


def chunk_size() -> int:
    return _env_int("CHUNK_SIZE", 300)


def chunk_overlap() -> int:
    return _env_int("CHUNK_OVERLAP", 40)


def top_k() -> int:
    return _env_int("TOP_K", 5)


def context_turns() -> int:
    """上下文轮次上限(注入的历史消息条数);<=0 表示不限制。"""
    try:
        return int(llm_config().get("context_turns", 24))
    except (TypeError, ValueError):
        return 24


def host() -> str:
    return env("HOST", "0.0.0.0") or "0.0.0.0"


def port() -> int:
    return _env_int("PORT", 8000)


def get_prompt(name: str) -> str:
    """读取 config/prompts/<name>.md,缺失返回空串。"""
    return _cached(PROMPT_DIR / f"{name}.md",
                   lambda p: p.read_text(encoding="utf-8")) or ""


def get_schema(name: str) -> dict | None:
    """读取 config/schemas/<name>.json。"""
    return _cached(SCHEMA_DIR / f"{name}.json",
                   lambda p: json.loads(p.read_text(encoding="utf-8")))


def ontology_schema() -> dict:
    """本体 Schema:对象类型 + 链接类型(config/ontology_schema.yaml,热加载)。"""
    data = _cached(CONFIG_DIR / "ontology_schema.yaml",
                   lambda p: yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return data or {"object_types": {}, "link_types": {}}


DEFAULT_AGENTS = {
    "student": {"identity": "student", "domains": ["domain-a"]},
    "teacher": {"identity": "teacher", "domains": ["domain-b"]},
    "platform": {"identity": "org", "domains": ["domain-c"]},
}


def agents_config() -> dict:
    """智能体引用范围配置(config/agents.yaml,热加载)。
    每个入口配置对接的知识域(domains);旧版 kbs 键仍兼容(解析为其所属知识域)。"""
    ensure_dirs()
    p = CONFIG_DIR / "agents.yaml"
    if not p.exists():
        p.write_text(
            "# 智能体引用范围:每个入口对接列出的知识域,范围外的知识域/知识库内容不参与 RAG\n"
            + yaml.safe_dump(DEFAULT_AGENTS, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    data = _cached(p, lambda x: yaml.safe_load(x.read_text(encoding="utf-8")) or {}) or {}
    merged = {k: dict(v) for k, v in DEFAULT_AGENTS.items()}
    for k, v in data.items():
        if isinstance(v, dict):
            merged.setdefault(k, {}).update(v)
    return merged
