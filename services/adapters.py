"""
URUK Trinity Console — LLM Adapters (v1.0)

Thin async wrappers around different LLM backends so the rest of the codebase
calls a single `adapter.call(messages, model, temperature, max_tokens) -> str`
interface regardless of provider.

Included adapters
-----------------
  XAIAdapter          xAI Grok API (OpenAI-compatible)
  GoogleAdapter       Gemini API via OpenAI-compat shim
  DesktopRelayAdapter Claude/Codex/ChatGPT Desktop via app_controller
  BrowserRelayAdapter Web-based LLMs (grok.com / gemini.google.com) via Chrome MCP

ADAPTERS dict maps provider keys used in nodes.yaml to adapter instances.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx


# ─────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────

class BaseAdapter:
    """All adapters implement this interface."""

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────
# xAI / Grok (OpenAI-compatible REST API)
# ─────────────────────────────────────────────────────────────────

class XAIAdapter(BaseAdapter):
    """Calls the xAI Grok API at https://api.x.ai/v1 (OpenAI-compat)."""

    DEFAULT_BASE = "https://api.x.ai/v1"

    def __init__(self, api_key: str = "", api_base: str = ""):
        self.api_base = (api_base or self.DEFAULT_BASE).rstrip("/")
        self.api_key  = api_key or os.environ.get("XAI_API_KEY", "")

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str = "grok-3",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        if not self.api_key:
            raise ValueError("XAI_API_KEY not set. Add it to config/.env or Settings.")
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────────
# Google Gemini (OpenAI-compatible shim)
# ─────────────────────────────────────────────────────────────────

class GoogleAdapter(BaseAdapter):
    """Calls Gemini via its OpenAI-compatible REST shim."""

    DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"

    def __init__(self, api_key: str = "", api_base: str = ""):
        self.api_base = (api_base or self.DEFAULT_BASE).rstrip("/")
        self.api_key  = api_key or os.environ.get("GEMINI_API_KEY", "")

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set. Add it to config/.env or Settings.")
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────────
# Desktop relay (Claude Desktop / ChatGPT Desktop / Copilot / Codex)
# ─────────────────────────────────────────────────────────────────

class DesktopRelayAdapter(BaseAdapter):
    """Relay via a local desktop app (Claude Desktop, ChatGPT Desktop, Copilot, Codex).

    Uses app_controller.send_and_receive under the hood; the `model` argument
    is the app_key (e.g. "claude", "chatgpt", "copilot", "codex").
    """

    def __init__(self, app_key: str, timeout: float = 180.0):
        self.app_key = app_key
        self.timeout = timeout

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        from services.app_controller import send_and_receive

        app_key = model or self.app_key
        user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        sys_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        combined = f"{sys_msg}\n\n{user_msg}" if sys_msg else user_msg

        result = await send_and_receive(app_key, combined, timeout=self.timeout)
        if not result.get("ok"):
            raise RuntimeError(
                f"DesktopRelayAdapter({app_key}): {result.get('error', 'relay failed')}"
            )
        return result.get("response", "")


# ─────────────────────────────────────────────────────────────────
# Browser relay (Grok Web / Gemini Web)
# ─────────────────────────────────────────────────────────────────

class BrowserRelayAdapter(BaseAdapter):
    """Relay via browser automation for web-based LLMs without an API key.

    Target URLs:
      grok_web   → https://grok.com
      gemini_web → https://gemini.google.com

    Requires the Claude-in-Chrome MCP extension to be connected.
    Falls back with a clear error message when the extension is unavailable.
    """

    # Input selectors to try per site (in order)
    _SELECTORS: Dict[str, List[str]] = {
        "grok.com": [
            "[data-testid='grok-input']",
            "textarea[placeholder]",
            "div[contenteditable='true']",
        ],
        "gemini.google.com": [
            "[data-testid='bubble-composer']",
            "rich-textarea .ql-editor",
            "div[contenteditable='true']",
        ],
    }

    def __init__(self, default_base: str = ""):
        self.default_base = default_base

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        target_url = model or self.default_base
        user_msg = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        sys_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        combined = f"{sys_msg}\n\n{user_msg}" if sys_msg else user_msg

        try:
            return await self._relay_via_chrome(target_url, combined)
        except NotImplementedError:
            return (
                f"[BrowserRelayAdapter: {target_url} requires the Claude-in-Chrome "
                "MCP extension. Connect it and retry, or use the API-backed provider instead.]"
            )
        except Exception as exc:
            return f"[BrowserRelayAdapter: {target_url} unavailable — {type(exc).__name__}: {exc}]"

    async def _relay_via_chrome(self, target_url: str, prompt: str) -> str:
        """Navigate to target_url, inject prompt, wait for response.

        This method is intentionally left as NotImplementedError so that the
        Chrome MCP tool calls can be wired in by the caller at runtime.
        The caller (e.g. a Skill or the main pipeline) should override this
        class or monkey-patch this method with the actual Chrome MCP logic.

        Expected Chrome MCP flow:
          1. navigate(target_url)
          2. find / fill the input field
          3. submit (Enter)
          4. wait for response to stop streaming
          5. extract and return the response text
        """
        raise NotImplementedError(
            "BrowserRelayAdapter._relay_via_chrome requires Chrome MCP extension wiring."
        )


# ─────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────

ADAPTERS: Dict[str, Any] = {
    # API-backed
    "xai":         XAIAdapter(),
    "grok":        XAIAdapter(),          # alias
    "google":      GoogleAdapter(),
    "gemini":      GoogleAdapter(),       # alias

    # Desktop relay
    "claude_desktop":   DesktopRelayAdapter("claude",   timeout=180.0),
    "codex_desktop":    DesktopRelayAdapter("codex",    timeout=180.0),
    "chatgpt_desktop":  DesktopRelayAdapter("chatgpt",  timeout=180.0),
    "copilot_desktop":  DesktopRelayAdapter("copilot",  timeout=180.0),

    # Browser relay (web, no API key required)
    "grok_web":    BrowserRelayAdapter(default_base="https://grok.com"),
    "gemini_web":  BrowserRelayAdapter(default_base="https://gemini.google.com"),
}


def get_adapter(provider: str) -> Optional[BaseAdapter]:
    """Return the adapter for a provider key, or None if not registered."""
    return ADAPTERS.get(provider)
