"""
URUK Trinity Console — Local LLM Discovery (v8.47)

Probes well-known localhost ports to find running local LLM applications.
Each app is fingerprinted by its HTTP API shape.

Supported apps:
  - Ollama          :11434  native API
  - LM Studio       :1234   OpenAI-compat
  - Jan             :1337   OpenAI-compat
  - KoboldCpp       :5001   hybrid (OpenAI-compat /v1 + kobold /api/v1)
  - Oobabooga/text-gen-webui :5000 OpenAI-compat extension
  - LocalAI         :8080   OpenAI-compat  (skipped if same as server port)
  - llama.cpp srv   :8081   OpenAI-compat
  - Open WebUI      :3000   proxies Ollama
  - AnythingLLM     :3001   OpenAI-compat wrapper
  - llamafile       :8080 / :8082  OpenAI-compat
  - GPT4All srv     :4891   OpenAI-compat
  - MistralRS       :1111   OpenAI-compat

Public API
----------
  await scan(own_port=8080, timeout=2.5)  -> list[AppInfo]
  await quick_chat(api_base, provider, model, message, timeout=30) -> str
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_LOCAL_WORKER_SYSTEM = (
    "You are a bounded local worker operating inside the URUK protocol carrier. "
    "Follow the requested task, language, and output format exactly. "
    "Do not claim final authority, invent system state, or expand the task."
)


# -----------------------------------------------------------------
# App descriptors — extend here to support more apps
# -----------------------------------------------------------------

_PROBE_TIMEOUT = 2.5   # seconds per probe attempt

_APPS: List[Dict[str, Any]] = [
    {
        "name": "Ollama",
        "port": 11434,
        "icon": "🦙",
        "provider": "ollama",
        "probe": "GET /api/tags",
        "models_fn": lambda d: [m["name"] for m in d.get("models", [])],
        "chat_path": "/api/chat",
    },
    {
        "name": "LM Studio",
        "port": 1234,
        "icon": "🎬",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "Jan",
        "port": 1337,
        "icon": "📦",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "KoboldCpp",
        "port": 5001,
        "icon": "⚙",
        "provider": "openai",
        "probe": "GET /api/v1/model",
        "models_fn": lambda d: [d["result"]] if d.get("result") else [],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "Oobabooga",
        "port": 5000,
        "icon": "🍄",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "LocalAI",
        "port": 8080,
        "icon": "🤖",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "llama.cpp",
        "port": 8081,
        "icon": "🦙",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "llamafile",
        "port": 8082,
        "icon": "📄",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "Open WebUI",
        "port": 3000,
        "icon": "🌐",
        "provider": "openai",
        "probe": "GET /api/v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/api/v1/chat/completions",
    },
    {
        "name": "AnythingLLM",
        "port": 3001,
        "icon": "💡",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "GPT4All",
        "port": 4891,
        "icon": "🧠",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
    {
        "name": "MistralRS",
        "port": 1111,
        "icon": "💨",
        "provider": "openai",
        "probe": "GET /v1/models",
        "models_fn": lambda d: [m["id"] for m in d.get("data", [])],
        "chat_path": "/v1/chat/completions",
    },
]


# -----------------------------------------------------------------
# AppInfo — result of a successful probe
# -----------------------------------------------------------------

class AppInfo:
    __slots__ = ("name", "icon", "port", "provider", "api_base",
                 "chat_path", "models", "status")

    def __init__(self, *, name, icon, port, provider, api_base,
                 chat_path, models, status="online"):
        self.name      = name
        self.icon      = icon
        self.port      = port
        self.provider  = provider
        self.api_base  = api_base
        self.chat_path = chat_path
        self.models    = models
        self.status    = status

    def to_dict(self) -> dict:
        return {
            "name":      self.name,
            "icon":      self.icon,
            "port":      self.port,
            "provider":  self.provider,
            "api_base":  self.api_base,
            "chat_path": self.chat_path,
            "models":    self.models,
            "status":    self.status,
        }


# -----------------------------------------------------------------
# Core probe
# -----------------------------------------------------------------

async def _probe_app(app: Dict[str, Any], own_port: int) -> Optional[AppInfo]:
    port = app["port"]
    if port == own_port:
        return None   # skip our own server

    method, path = app["probe"].split(" ", 1)
    base = f"http://localhost:{port}"
    url  = base + path

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            if method == "GET":
                r = await client.get(url)
            else:
                r = await client.post(url)

            if r.status_code >= 400:
                return None

            try:
                data = r.json()
            except Exception:
                data = {}

            models = []
            try:
                models = app["models_fn"](data)
            except Exception:
                pass

            if app["provider"] == "ollama":
                api_base = base
            else:
                api_base = base

            return AppInfo(
                name=app["name"],
                icon=app["icon"],
                port=port,
                provider=app["provider"],
                api_base=api_base,
                chat_path=app["chat_path"],
                models=models[:30],
                status="online",
            )

    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
            OSError, Exception):
        return None


# -----------------------------------------------------------------
# Public: scan all apps concurrently
# -----------------------------------------------------------------

async def scan(own_port: int = 8080) -> List[AppInfo]:
    """Probe all known local LLM endpoints concurrently.
    Returns list of AppInfo for discovered (online) apps."""
    tasks = [_probe_app(app, own_port) for app in _APPS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    found = []
    for r in results:
        if isinstance(r, AppInfo):
            found.append(r)
    return found


# -----------------------------------------------------------------
# Public: quick direct chat (no Trinity pipeline)
# Supports: ollama / anthropic / openai-compat (default)
# -----------------------------------------------------------------

async def _quick_chat_inner(
    api_base: str,
    provider: str,
    model: str,
    message: str,
    system: str = "你係 URUK 協議載體嘅直接回應模式，用廣東話回答。",
    timeout: float = 60.0,
    api_key: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.2,
    think: bool = False,
    keep_alive: str = "15m",
    context_window: int = 8192,
) -> str:
    """Send a single message to a local or cloud LLM and return its text reply."""
    import os as _os

    if not system or system.count("?") >= 5:
        system = DEFAULT_LOCAL_WORKER_SYSTEM

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": message})

    # ── Ollama native ──────────────────────────────────────────
    if provider == "ollama":
        url = api_base.rstrip("/") + "/api/chat"
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": bool(think),
            "keep_alive": keep_alive,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
                "num_ctx": int(context_window),
            },
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            return r.json()["message"]["content"]

    # ── Anthropic Messages API ─────────────────────────────────
    elif provider == "anthropic":
        _key = api_key or _os.environ.get("ANTHROPIC_API_KEY", "")
        if not _key:
            raise ValueError(
                "No Anthropic API key. Set ANTHROPIC_API_KEY in config/.env."
            )
        _url = "https://api.anthropic.com/v1/messages"
        _hdrs = {
            "x-api-key": _key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        # Anthropic does not accept a system role in the messages array
        _usr_msgs = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] != "system"
        ]
        _bdy = {
            "model": model,
            "max_tokens": int(max_tokens),
            "messages": _usr_msgs,
        }
        if system:
            _bdy["system"] = system
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(_url, headers=_hdrs, json=_bdy)
            r.raise_for_status()
            return r.json()["content"][0]["text"]

    # ── OpenAI-compatible ──────────────────────────────────────
    else:
        url = api_base.rstrip("/") + "/v1/chat/completions"
        body = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


async def quick_chat(
    api_base: str,
    provider: str,
    model: str,
    message: str,
    system: str = "你係 URUK 協議載體嘅直接回應模式，用廣東話回答。",
    timeout: float = 60.0,
    api_key: str = "",
    max_tokens: int = 2048,
    role: str = "quick_chat",
    temperature: float = 0.2,
    think: bool = False,
    keep_alive: str = "15m",
    context_window: int = 8192,
) -> str:
    """Tracked public wrapper for a direct local/cloud model request."""
    from services.inference_governor import execute_model_call

    return await execute_model_call(
        lambda: _quick_chat_inner(
            api_base=api_base,
            provider=provider,
            model=model,
            message=message,
            system=system,
            timeout=timeout,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            think=think,
            keep_alive=keep_alive,
            context_window=context_window,
        ),
        role=role,
        provider=provider,
        model=model,
    )
