"""火山方舟(OpenAI 兼容)统一 LLM 客户端。

能力:chat(含 function-call)/ chat_stream / extract_json(结构化抽取)/
     embed(向量化,维度自动捕获)/ rerank(重排,默认 llm 打分兜底策略)。

模型名与参数全部来自 data/config/llm.yaml(热加载);密钥仅读环境变量 ARK_API_KEY。
对外只抛 LLMError,调用方据此统一降级为"请稍后重试"。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Iterator

from openai import OpenAI

from . import config

log = logging.getLogger(__name__)

_client: OpenAI | None = None
_client_ident: tuple | None = None
_embed_client: OpenAI | None = None
_embed_client_ident: tuple | None = None


class LLMError(RuntimeError):
    """模型调用失败的统一异常。"""


def client() -> OpenAI:
    """对话客户端(凭证来自 config.chat_credentials)。"""
    global _client, _client_ident
    cfg = config.llm_config()
    key, base_url = config.chat_credentials()
    if not key:
        raise LLMError("未配置对话 API Key(请在仓库根 .env 设置 VOLCANO_API_KEY 或 ARK_API_KEY)")
    ident = (base_url, key)
    if _client is None or _client_ident != ident:
        _client = OpenAI(base_url=base_url, api_key=key,
                         timeout=cfg.get("request_timeout", 60))
        _client_ident = ident
    return _client


def _embed_client_get() -> tuple[OpenAI, str]:
    """向量化客户端(可为独立服务),返回 (client, model)。"""
    global _embed_client, _embed_client_ident
    cfg = config.llm_config()
    key, base_url, model = config.embed_credentials()
    if not key:
        raise LLMError("未配置向量化 API Key(ARK_EMBED_KEY 或 VOLCANO_API_KEY)")
    ident = (base_url, key, model)
    if _embed_client is None or _embed_client_ident != ident:
        _embed_client = OpenAI(base_url=base_url, api_key=key,
                               timeout=cfg.get("request_timeout", 60))
        _embed_client_ident = ident
    return _embed_client, model


def chat(messages: list[dict], *, tools: list[dict] | None = None,
         tool_choice: Any = None, temperature: float | None = None,
         max_tokens: int | None = None, model: str | None = None):
    """同步 chat,内置 3 次重试。返回 message 对象。"""
    cfg = config.llm_config()
    kwargs: dict[str, Any] = {
        "model": model or cfg["chat_model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3) if temperature is None else temperature,
        "max_tokens": max_tokens or cfg.get("max_tokens", 2048),
    }
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = client().chat.completions.create(**kwargs)
            return resp.choices[0].message
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("chat 第 %d 次失败: %s", attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))
    raise LLMError(f"模型服务暂时不可用: {last}")


def chat_stream(messages: list[dict], *, tools: list[dict] | None = None,
                temperature: float | None = None, model: str | None = None) -> Iterator:
    cfg = config.llm_config()
    kwargs: dict[str, Any] = {
        "model": model or cfg["chat_model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3) if temperature is None else temperature,
        "max_tokens": cfg.get("max_tokens", 2048),
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
    try:
        yield from client().chat.completions.create(**kwargs)
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"模型服务暂时不可用: {e}") from e


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def _parse_json(text: str) -> dict:
    text = _FENCE.sub("", text.strip()).strip()
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("响应中不含 JSON 对象")


def extract_json(system: str, user: str, schema: dict, *, name: str = "submit") -> dict:
    """按 JSON Schema 结构化抽取:优先 function-call,失败回退 content 解析。"""
    tools = [{
        "type": "function",
        "function": {"name": name, "description": "提交结构化抽取结果", "parameters": schema},
    }]
    try:
        msg = chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": name}},
            temperature=0,
        )
        if msg.tool_calls:
            return json.loads(msg.tool_calls[0].function.arguments)
        if msg.content:
            return _parse_json(msg.content)
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("function-call 抽取失败,回退纯 JSON 模式: %s", e)
    # 回退:纯 JSON 输出
    msg = chat([
        {"role": "system", "content": system + "\n严格按 JSON Schema 输出,只输出 JSON,不要任何解释。"},
        {"role": "user", "content": user},
    ], temperature=0)
    try:
        return _parse_json(msg.content or "")
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"结构化抽取失败: {e}") from e


# ---------- embedding ----------

_embed_dim: int | None = None


def embed(texts: list[str]) -> list[list[float]]:
    global _embed_dim
    if not texts:
        return []
    texts = [t if t.strip() else " " for t in texts]
    cli, model = _embed_client_get()
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = cli.embeddings.create(model=model, input=texts)
            vecs = [d.embedding for d in resp.data]
            if vecs:
                _embed_dim = len(vecs[0])
            return vecs
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("embed 第 %d 次失败: %s", attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))
    raise LLMError(f"向量化失败: {last}")


def embed_dim() -> int | None:
    return _embed_dim


# ---------- rerank ----------

def rerank(query: str, docs: list[str], top_n: int = 5) -> list[tuple[int, float]]:
    """重排,返回 [(原索引, 分数)] 按分数降序。

    strategy=endpoint 调 /rerank 兼容端点(需配 rerank_url);
    默认 llm 策略:让模型对候选逐条打 0-10 分,任何环境可用。
    """
    if not docs:
        return []
    cfg = config.llm_config()
    if cfg.get("rerank_strategy") == "endpoint":
        try:
            return _rerank_endpoint(cfg, query, docs, top_n)
        except Exception as e:  # noqa: BLE001
            log.warning("rerank endpoint 不可用,回退 llm 策略: %s", e)
    return _rerank_llm(query, docs, top_n)


def _rerank_endpoint(cfg: dict, query: str, docs: list[str], top_n: int):
    import httpx
    url = cfg.get("rerank_url") or cfg["base_url"].rstrip("/") + "/rerank"
    key = os.environ.get("ARK_API_KEY", "")
    r = httpx.post(url, json={"model": cfg.get("rerank_model"), "query": query,
                              "documents": docs, "top_n": top_n},
                   headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    items = r.json().get("results", [])
    return [(int(i["index"]), float(i.get("relevance_score", 0))) for i in items][:top_n]


def _rerank_llm(query: str, docs: list[str], top_n: int) -> list[tuple[int, float]]:
    listing = "\n".join(f"[{i}] {d[:300]}" for i, d in enumerate(docs))
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "score": {"type": "number", "description": "相关性 0-10"},
                    },
                    "required": ["index", "score"],
                },
            },
        },
        "required": ["items"],
    }
    out = extract_json(
        "你是搜索相关性评分专家。对每个候选文档与用户问题的相关性打 0-10 分"
        "(0=完全无关,10=直接回答)。每个候选都要打分。",
        f"问题:{query}\n候选文档:\n{listing}",
        schema, name="scores",
    )
    pairs = []
    for it in out.get("items", []):
        try:
            idx, score = int(it["index"]), float(it["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(docs):
            pairs.append((idx, score))
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs[:top_n]
