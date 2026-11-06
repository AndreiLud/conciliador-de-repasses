"""Local LLM adapter with a versioned response cache.

Providers (``LLM_PROVIDER``):
* ``ollama``   : Ollama server, POST /api/chat with a JSON schema in ``format``;
* ``llamacpp`` : any OpenAI compatible local server (llama.cpp ``llama-server``,
                 LM Studio), POST /v1/chat/completions with ``response_format``.

Modes (``LLM_MODE``):
* ``cache_first`` (default): answer from llm_cache/ when possible, call the
  local server otherwise;
* ``offline``: never call a server; a cache miss is reported, and the caller
  falls back to the deterministic path (template text or human review);
* ``live``: always call the server and refresh the cache.

Every call records tokens and seconds; the cache stores them too, so a run
replayed from cache still reports what the original run consumed.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .. import config


class CacheMiss(RuntimeError):
    pass


class ProviderError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    provider: str = "llamacpp"
    model: str = "qwen3.5-2b-q4_k_m"
    base_url: str = "http://127.0.0.1:8080"
    mode: str = "cache_first"
    timeout: float = 600.0
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 4096

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = config.env("LLM_PROVIDER", "llamacpp")
        default_url = "http://127.0.0.1:11434" if provider == "ollama" else "http://127.0.0.1:8080"
        return cls(provider=provider,
                   model=config.env("LLM_MODEL", cls.model),
                   base_url=config.env("LLM_BASE_URL", default_url),
                   mode=config.env("LLM_MODE", "cache_first"),
                   timeout=float(config.env("LLM_TIMEOUT", "600")))


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    seconds: float
    cached: bool
    key: str


@dataclass
class UsageStats:
    calls: int = 0
    cache_hits: int = 0
    cache_misses_offline: int = 0
    new_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0          # machine time recorded for the answers used in this run
    new_seconds: float = 0.0      # machine time spent in this run (zero when replayed from cache)
    by_task: dict = field(default_factory=dict)

    def add(self, task: str, r: LLMResponse) -> None:
        self.calls += 1
        self.cache_hits += int(r.cached)
        self.new_calls += int(not r.cached)
        self.tokens_in += r.tokens_in
        self.tokens_out += r.tokens_out
        self.seconds += r.seconds
        if not r.cached:
            self.new_seconds += r.seconds
        t = self.by_task.setdefault(task, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "seconds": 0.0})
        t["calls"] += 1
        t["tokens_in"] += r.tokens_in
        t["tokens_out"] += r.tokens_out
        t["seconds"] += r.seconds


class ResponseCache:
    def __init__(self, root: Path = config.LLM_CACHE_DIR):
        self.root = root

    def path(self, task: str, key: str) -> Path:
        return self.root / task / f"{key[:16]}.json"

    def get(self, task: str, key: str) -> dict | None:
        p = self.path(task, key)
        if not p.exists():
            return None
        entry = json.loads(p.read_text(encoding="utf-8"))
        return entry if entry.get("key") == key else None

    def put(self, task: str, key: str, entry: dict) -> None:
        p = self.path(task, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")


def cache_key(task: str, model: str, system: str, user: str, schema: dict) -> str:
    payload = json.dumps({"task": task, "model": model, "system": system, "user": user, "schema": schema},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LLMClient:
    def __init__(self, cfg: LLMConfig | None = None, cache: ResponseCache | None = None):
        self.cfg = cfg or LLMConfig.from_env()
        self.cache = cache or ResponseCache()
        self.stats = UsageStats()
        self.used_files: set[Path] = set()
        self._http = None

    # -- providers
    def _post(self, url: str, body: dict) -> dict:
        if self._http is None:
            self._http = httpx.Client(timeout=self.cfg.timeout)
        try:
            resp = self._http.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"{self.cfg.provider} at {url}: answer is not JSON") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.cfg.provider} at {url}: {exc}") from exc

    def _call_ollama(self, system: str, user: str, schema: dict) -> tuple[str, int, int]:
        data = self._post(f"{self.cfg.base_url}/api/chat", {
            "model": self.cfg.model, "stream": False, "think": False, "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": self.cfg.temperature, "seed": self.cfg.seed, "num_ctx": self.cfg.num_ctx},
        })
        try:
            return (data["message"]["content"] or "", int(data.get("prompt_eval_count", 0)),
                    int(data.get("eval_count", 0)))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"unexpected answer from ollama: {str(data)[:200]}") from exc

    def _call_openai_compat(self, system: str, user: str, schema: dict) -> tuple[str, int, int]:
        data = self._post(f"{self.cfg.base_url}/v1/chat/completions", {
            "model": self.cfg.model, "temperature": self.cfg.temperature, "seed": self.cfg.seed,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "schema": schema,
                                "json_schema": {"name": "resposta", "schema": schema, "strict": True}},
            "chat_template_kwargs": {"enable_thinking": False},
        })
        try:
            usage = data.get("usage") or {}
            content = data["choices"][0]["message"]["content"] or ""
            return content, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError(f"unexpected answer from the local server: {str(data)[:200]}") from exc

    def available(self) -> bool:
        if self.cfg.mode == "offline":
            return False
        url = f"{self.cfg.base_url}/api/tags" if self.cfg.provider == "ollama" else f"{self.cfg.base_url}/health"
        try:
            return httpx.get(url, timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    # -- public
    def complete_json(self, task: str, system: str, user: str, schema: dict) -> LLMResponse:
        key = cache_key(task, self.cfg.model, system, user, schema)
        if self.cfg.mode != "live":
            entry = self.cache.get(task, key)
            if entry is not None:
                self.used_files.add(self.cache.path(task, key))
                r = LLMResponse(entry["response"], entry["usage"]["tokens_in"], entry["usage"]["tokens_out"],
                                entry["usage"]["seconds"], True, key)
                self.stats.add(task, r)
                return r
        if self.cfg.mode == "offline":
            self.stats.cache_misses_offline += 1
            raise CacheMiss(f"{task}:{key[:12]}")
        t0 = time.perf_counter()
        if self.cfg.provider == "ollama":
            content, tin, tout = self._call_ollama(system, user, schema)
        else:
            content, tin, tout = self._call_openai_compat(system, user, schema)
        seconds = round(time.perf_counter() - t0, 2)
        r = LLMResponse(content, tin, tout, seconds, False, key)
        self.cache.put(task, key, {
            "key": key, "task": task, "provider": self.cfg.provider, "model": self.cfg.model,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "system_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
            "user": user, "response": content,
            "usage": {"tokens_in": tin, "tokens_out": tout, "seconds": seconds},
        })
        self.used_files.add(self.cache.path(task, key))
        self.stats.add(task, r)
        return r

    def prune_cache(self) -> int:
        """Delete cached answers of the tasks this run used that are no longer reachable (old prompts or
        inputs). Tasks that did not run (for example letters with LETTERS_AI off) are left untouched."""
        removed = 0
        tasks = {f.parent.name for f in self.used_files}
        for f in self.cache.root.rglob("*.json"):
            if f.parent.name in tasks and f not in self.used_files:
                f.unlink()
                removed += 1
        return removed
