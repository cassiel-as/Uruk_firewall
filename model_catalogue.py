"""
Known-good model list per provider — used by Settings UI for the model
combobox (HTML5 datalist). Freeform input remains the source-of-truth;
this catalogue only provides dropdown hints for the most common models.

Update this list manually when providers release new models. Stale entries
don't break anything — user can still type any model name verbatim.
"""

from __future__ import annotations

from typing import Dict, List


# Map: provider name (matches PROVIDERS_CATALOGUE) → ordered list of model strings.
# Order matters — first ~3 entries appear most prominently in dropdown.
KNOWN_MODELS: Dict[str, List[str]] = {
    # ─── Pay-per-token APIs ───
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "o1-preview",
        "o1-mini",
    ],
    "anthropic": [
        "claude-opus-4-5-20250514",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20251001",
        "claude-3-5-sonnet-20241022",
    ],
    "google": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash-exp",
        "gemini-1.5-pro",
    ],
    "xai": [
        "grok-2-latest",
        "grok-2-1212",
        "grok-beta",
    ],

    # ─── Free-tier / aggregator routes ───
    "openrouter": [
        "openai/gpt-oss-120b:free",
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-r1:free",
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o",
        "x-ai/grok-2",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
        "deepseek-r1-distill-llama-70b",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
    ],
    "cerebras": [
        # Cerebras free-tier active list (2026-05-17): operator confirmed only
        # `llama3.1-8b` is exposed on their dashboard. Other names removed
        # rather than guessed — users can type freeform if Cerebras adds models.
        "llama3.1-8b",
    ],

    # ─── v8.3 additions ───
    "nvidia": [
        "deepseek-ai/deepseek-r1",
        "moonshotai/kimi-k2.5-instruct",
        "zhipuai/glm-5",
        "meta/llama-3.3-70b-instruct",
        "mistralai/mixtral-8x22b-instruct-v0.1",
        "qwen/qwen2.5-72b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
    ],
    "sambanova": [
        "Meta-Llama-3.1-405B-Instruct",
        "Meta-Llama-3.1-70B-Instruct",
        "Meta-Llama-3.1-8B-Instruct",
        "DeepSeek-R1",
        "DeepSeek-V3",
        "Qwen2.5-72B-Instruct",
    ],
    "cloudflare": [
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "@cf/meta/llama-3.1-8b-instruct",
        "@cf/qwen/qwq-32b",
        "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        "@cf/mistralai/mistral-small-3.1-24b-instruct",
    ],
    "chutes": [
        "deepseek-ai/DeepSeek-R1",
        "deepseek-ai/DeepSeek-V3",
        "meta-llama/Llama-3.3-70B-Instruct",
        "Qwen/Qwen2.5-72B-Instruct",
    ],
    "hyperbolic": [
        "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "openai/gpt-oss-120b",
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-R1",
        "meta-llama/Meta-Llama-3.1-405B-Instruct",
        "meta-llama/Meta-Llama-3.1-70B-Instruct",
    ],
    "pollinations": [
        "openai",
        "mistral",
        "llama",
        "qwen-coder",
        "deepseek",
        "claude",
    ],

    # ─── Local ───
    "ollama": [
        "qwen2.5:3b",
        "qwen2.5:7b",
        "llama3.2:3b",
        "llama3.3:70b",
        "mistral:7b",
        "gemma2:9b",
    ],
    "codex_desktop": [
        "codex",
    ],
    "claude_desktop": [
        "claude_desktop",
    ],
    "chatgpt_desktop": [
        "chatgpt",
    ],
    "copilot_desktop": [
        "copilot",
    ],
}


def models_for(provider: str) -> List[str]:
    """Return list of known model strings for a provider. Empty list if unknown."""
    return KNOWN_MODELS.get(provider, [])
