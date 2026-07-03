"""
Unified LLM adapters for Trinity Console.

Each adapter exposes the same async interface:
    async def call(messages, model, temperature, max_tokens) -> str

Supported providers:
  - OpenAI (and OpenAI-compatible: OpenRouter, etc.)
  - Anthropic
  - Google Gemini
  - xAI Grok
  - Ollama (local)
  - Desktop relay: Claude / Codex / ChatGPT / Windows Copilot
"""

from abc import ABC, abstractmethod
from functools import wraps
from typing import List, Dict, Optional
import os
import re
import httpx


def _adapter_provider(adapter) -> str:
    name = type(adapter).__name__.replace("Adapter", "").casefold()
    base = str(getattr(adapter, "api_base", "") or "").casefold()
    if "openrouter" in base:
        return "openrouter"
    if "groq" in base:
        return "groq"
    if "cerebras" in base:
        return "cerebras"
    if "gemini" in name or "google" in name:
        return "gemini"
    if "anthropic" in name:
        return "anthropic"
    if "ollama" in name:
        return "ollama"
    if "desktoprelay" in name or name in {"codexdesktop", "claudedesktop", "chatgptdesktop", "copilotdesktop"}:
        return f"{getattr(adapter, 'app_key', name)}_desktop"
    if "xai" in name:
        return "xai"
    return name or "unknown"


class BaseAdapter(ABC):
    def __init_subclass__(cls, **kwargs):
        """Wrap every concrete adapter call with request-level inference telemetry."""
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get("call")
        if original is None or getattr(original, "_uruk_inference_wrapped", False):
            return

        @wraps(original)
        async def tracked(self, messages, model, temperature=0.7, max_tokens=4096):
            from services.inference_governor import execute_model_call

            return await execute_model_call(
                lambda: original(self, messages, model, temperature, max_tokens),
                provider=_adapter_provider(self),
                model=str(model or "unknown"),
            )

        tracked._uruk_inference_wrapped = True
        cls.call = tracked

    def __init__(self, api_key: Optional[str] = None, api_base: Optional[str] = None):
        self.api_key = api_key
        self.api_base = api_base

    @abstractmethod
    async def call(self, messages: List[Dict], model: str,
                   temperature: float = 0.7, max_tokens: int = 4096) -> str:
        ...


# ─────────────────────────────────────────────────────────────────
class OpenAIAdapter(BaseAdapter):
    """OpenAI / OpenRouter / any OpenAI chat-completions-compatible API."""

    DEFAULT_BASE = "https://api.openai.com/v1"

    async def call(self, messages, model, temperature=0.7, max_tokens=4096):
        base = self.api_base or self.DEFAULT_BASE
        # v8.3: substitute environment-derived template tokens (e.g. Cloudflare
        # account ID baked into the URL path). Pattern matches `{ENV_VAR_NAME}`
        # and replaces with `os.environ[ENV_VAR_NAME]` value (or empty string).
        if base and "{" in base:
            base = re.sub(
                r"\{([A-Z_][A-Z0-9_]*)\}",
                lambda m: os.environ.get(m.group(1), ""),
                base,
            )
        headers = {"Content-Type": "application/json"}
        # v8.3: Pollinations (and similar anonymous endpoints) don't require auth.
        # Skip the Bearer header entirely if api_key is blank — some servers reject
        # `Authorization: Bearer ` (with empty value) as malformed.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # OpenRouter requires these
        if "openrouter" in (base or ""):
            headers.update({
                "HTTP-Referer": "https://github.com/cassiel-as/uruk-trinity-console",
                "X-Title": "URUK Trinity Console",
            })
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            r.raise_for_status()
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            content = msg.get("content")
            if content:
                # Strip leading <think>...</think> reasoning blocks emitted inline
                # by some models (qwen3, etc.) so they never reach the user output.
                content = re.sub(r"^\s*<think>.*?</think>\s*", "", content,
                                 flags=re.DOTALL).strip()
            if not content:
                # Reasoning models put hidden reasoning in a separate field that
                # still counts against max_tokens; if the budget was exhausted the
                # visible content comes back empty. Raise so the (fast) failover
                # chain can retry on another model instead of emitting a blank node.
                finish = choice.get("finish_reason", "")
                raise RuntimeError(
                    f"OpenAI-compat empty content (finish_reason={finish}, model={model})"
                )
            return content


# ─────────────────────────────────────────────────────────────────
class AnthropicAdapter(BaseAdapter):
    """Anthropic Messages API."""

    DEFAULT_BASE = "https://api.anthropic.com/v1"

    async def call(self, messages, model, temperature=0.7, max_tokens=4096):
        base = self.api_base or self.DEFAULT_BASE
        # Anthropic separates system from messages
        system_parts = []
        msgs = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        system = "\n\n".join(system_parts)

        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{base}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": msgs,
                    "temperature": temperature,
                },
            )
            r.raise_for_status()
            data = r.json()
            return data["content"][0]["text"]


# ─────────────────────────────────────────────────────────────────
class GoogleAdapter(BaseAdapter):
    """Google Gemini API."""

    DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"

    async def call(self, messages, model, temperature=0.7, max_tokens=4096):
        base = self.api_base or self.DEFAULT_BASE
        # Convert OpenAI-style messages to Gemini format
        system_parts = []
        contents = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            elif m["role"] == "user":
                contents.append({"role": "user", "parts": [{"text": m["content"]}]})
            elif m["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": m["content"]}]})

        # Gemini supports systemInstruction since v1beta
        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{base}/models/{model}:generateContent",
                params={"key": self.api_key},
                json=body,
            )
            r.raise_for_status()
            data = r.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Gemini response unexpected: {data}") from e


# ─────────────────────────────────────────────────────────────────
class XAIAdapter(OpenAIAdapter):
    """xAI Grok — uses OpenAI-compatible API."""

    DEFAULT_BASE = "https://api.x.ai/v1"


# ─────────────────────────────────────────────────────────────────
class OllamaAdapter(BaseAdapter):
    """Local Ollama instance."""

    DEFAULT_BASE = "http://localhost:11434"

    async def call(self, messages, model, temperature=0.7, max_tokens=4096):
        base = self.api_base or self.DEFAULT_BASE
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(
                f"{base}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            )
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"]


class DesktopRelayAdapter(BaseAdapter):
    """Desktop app relay adapter used as a failover backend."""

    app_key = ""

    @staticmethod
    def _format_messages(messages: List[Dict]) -> str:
        parts = []
        for msg in messages:
            role = str(msg.get("role", "user")).upper()
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(str(part) for part in content)
            parts.append(f"[{role}]\n{content}")
        return "\n\n".join(parts).strip()

    @staticmethod
    def _infer_relay_mode(model: str, prompt: str) -> str:
        model_l = (model or "").lower()
        if "upgrade" in model_l:
            return "upgrade"
        if "tool" in model_l and "design" in model_l:
            return "tool_design"
        if "review" in model_l:
            return "review"

        text = (prompt or "").lower()
        if "[upgrade_plan:" in text or "[upgrade_learn]" in text or "[tool_spec:" in text:
            return "upgrade"
        if "you are a tool designer" in text or "python_code" in text:
            return "tool_design"
        if "security review" in text or "layer b" in text or ('"pass"' in text and '"concerns"' in text):
            return "review"
        return "general"

    async def call(self, messages, model, temperature=0.7, max_tokens=4096):
        if not self.app_key:
            raise RuntimeError("desktop relay unavailable: app_key not configured")

        from services.app_controller import send_and_receive

        prompt = self._format_messages(messages)
        relay_mode = self._infer_relay_mode(model, prompt)
        timeout = max(90.0, min(600.0, float(max_tokens) / 12.0))
        result = await send_and_receive(
            self.app_key,
            prompt,
            timeout=timeout,
            relay_mode=relay_mode,
        )
        if not result.get("ok"):
            raise RuntimeError(
                f"desktop relay unavailable ({self.app_key}): {result.get('error', 'unknown error')}"
            )
        response = result.get("response")
        if response:
            return str(response)
        return str(result.get("message") or "")


class CodexDesktopAdapter(DesktopRelayAdapter):
    app_key = "codex"


class ClaudeDesktopAdapter(DesktopRelayAdapter):
    app_key = "claude"


class ChatGPTDesktopAdapter(DesktopRelayAdapter):
    app_key = "chatgpt"


class CopilotDesktopAdapter(DesktopRelayAdapter):
    app_key = "copilot"
