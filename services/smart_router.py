"""
URUK Smart Router — auto-routes LLM requests to the right backend (v1.0)

Backends (priority order within each tier):
  claude_desktop  — URUK protocol-carrier relay via Claude Desktop backend channel
                    Best for: Trinity/Uruk skills, project memory, deep analysis
  codex_desktop   — Codex Desktop via app_relay
                    Best for: code, upgrades, tool design, quota failover
  copilot_desktop — Windows Copilot via app_relay
                    Best for: Windows UI, file search, screenshots, settings
  ollama          — Local Ollama (free, offline)
                    Best for: fast tasks, simple Q&A, classification
  api             — Cloud API (paid token path)
                    Best for: fallback when others unavailable

Public API
----------
  route(prompt, available_backends) -> Backend
  explain(prompt, available_backends) -> dict  (for UI display)
"""

from __future__ import annotations
import re
from enum import Enum
from typing import Dict

from services.protocol_concepts import is_protocol_concept_query


class Backend(str, Enum):
    CLAUDE_DESKTOP = "claude_desktop"
    CODEX_DESKTOP  = "codex_desktop"
    COPILOT_DESKTOP = "copilot_desktop"
    OLLAMA         = "ollama"
    API            = "api"


# ── Keyword sets ──────────────────────────────────────────────────

_URUK_KEYWORDS = frozenset({
    "uruk", "firewall", "blackbox", "trinity", "kairos",
    "八律", "座標", "主權", "三位一體", "聖父", "聖子", "聖靈",
    "sovereign", "soul coordinate", "靈魂座標", "/news", "/blackbox", "/firewall", "/scr",
    "lie_cost", "freedom_loss", "freedom_loss_entropy",
    "自由", "自由度", "freedom", "liberty", "民主", "文明",
    "主權", "自治", "尊嚴", "存在", "意義", "真理", "價值",
    "靈魂", "抽象概念", "abstract concept", "(0,0,0)", "假設逆轉",
    "hidden coordinate", "隱藏座標",
})

_CODE_KEYWORDS = frozenset({
    "def ", "class ", "import ", "function", "async ", "await ",
    "bug", "error", "debug", "fix", "refactor",
    "代碼", "程式", "python", "javascript", "typescript", "golang",
    "sql", "bash", "shell", "dockerfile", "json", "yaml",
})

_WINDOWS_CONTEXT_KEYWORDS = frozenset({
    "windows", "copilot", "desktop", "screen", "screenshot", "file search",
    "setting", "settings", "taskbar", "start menu", "onedrive", "folder",
    "local file", "local files", "window", "ui", "vision",
})

_DEEP_KEYWORDS = frozenset({
    "分析", "analysis", "評估", "evaluate", "解釋", "explain",
    "比較", "compare", "策略", "strategy", "架構", "architecture",
    "原因", "reason", "因果", "causal", "為什麼", "why",
})

# ── Routing thresholds ────────────────────────────────────────────

_SHORT_THRESHOLD  = 120   # chars — simple query, prefer Ollama
_LONG_THRESHOLD   = 350   # chars — complex query, prefer desktop relay channel


# ── Core routing logic ────────────────────────────────────────────

_DEEP_KEYWORDS = _DEEP_KEYWORDS | frozenset({
    "分析", "比較", "評估", "風險", "因果", "策略", "設計", "架構", "點解",
})


def route(
    prompt: str,
    available_backends: Dict[str, bool],
) -> Backend:
    """
    available_backends keys: "claude_desktop", "codex_desktop",
    "copilot_desktop", "ollama", "api"
    Values: True if available, False otherwise.
    Returns the best Backend enum value.
    """
    lower = prompt.lower()
    has_cd  = available_backends.get("claude_desktop", False)
    has_cx  = available_backends.get("codex_desktop", False)
    has_cp  = available_backends.get("copilot_desktop", False)
    has_ol  = available_backends.get("ollama", False)
    has_api = available_backends.get("api", False)

    # ── Tier 1: Uruk/Trinity keywords → protocol-carrier relay channel ──
    if is_protocol_concept_query(prompt) or any(kw in lower for kw in _URUK_KEYWORDS):
        if has_cd:
            return Backend.CLAUDE_DESKTOP
        if has_cx:
            return Backend.CODEX_DESKTOP
        # Desktop not available -> fall to API before a small local model.
        if has_api:
            return Backend.API
        return Backend.CLAUDE_DESKTOP

    # ── Tier 2: Code keywords → Codex Desktop, then local model ───
    if any(kw in lower for kw in _CODE_KEYWORDS):
        if has_cx:
            return Backend.CODEX_DESKTOP
        if has_cd:
            return Backend.CLAUDE_DESKTOP
        if has_api:
            return Backend.API
        return Backend.CODEX_DESKTOP

    # ── Tier 2.5: Windows context tasks → Copilot Desktop ──
    if any(kw in lower for kw in _WINDOWS_CONTEXT_KEYWORDS):
        if has_cp:
            return Backend.COPILOT_DESKTOP
        if has_cx:
            return Backend.CODEX_DESKTOP
        if has_cd:
            return Backend.CLAUDE_DESKTOP
        if has_api:
            return Backend.API
        return Backend.COPILOT_DESKTOP

    # ── Tier 3: Length-based routing ──────────────────────────────
    # Reasoning and decision work must not be captured by the short-query rule.
    if any(kw in lower for kw in _DEEP_KEYWORDS):
        if has_cd:
            return Backend.CLAUDE_DESKTOP
        if has_cx:
            return Backend.CODEX_DESKTOP
        if has_api:
            return Backend.API
        return Backend.CLAUDE_DESKTOP

    n = len(prompt)

    if n < _SHORT_THRESHOLD:
        # Short + simple → Ollama first
        if has_ol:
            return Backend.OLLAMA
        if has_cx:
            return Backend.CODEX_DESKTOP
        if has_cd:
            return Backend.CLAUDE_DESKTOP
        if has_api:
            return Backend.API

    if n >= _LONG_THRESHOLD:
        # Long/complex -> Desktop paths before paid API.
        if has_cd:
            return Backend.CLAUDE_DESKTOP
        if has_cx:
            return Backend.CODEX_DESKTOP
        if has_api:
            return Backend.API
        return Backend.CLAUDE_DESKTOP

    # ── Tier 4: Deep analysis keywords (medium length) → Desktop ──
    if any(kw in lower for kw in _DEEP_KEYWORDS):
        if has_cd:
            return Backend.CLAUDE_DESKTOP
        if has_cx:
            return Backend.CODEX_DESKTOP
        if has_api:
            return Backend.API
        return Backend.CLAUDE_DESKTOP

    # ── Tier 5: Default fallback priority: Ollama -> Codex -> Claude -> Copilot -> API
    if has_ol:
        return Backend.OLLAMA
    if has_cx:
        return Backend.CODEX_DESKTOP
    if has_cd:
        return Backend.CLAUDE_DESKTOP
    if has_cp:
        return Backend.COPILOT_DESKTOP
    if has_api:
        return Backend.API

    # No backend available — return desktop as nominal target
    return Backend.CLAUDE_DESKTOP


def explain(
    prompt: str,
    available_backends: Dict[str, bool],
) -> dict:
    """
    Returns routing decision with human-readable reason.
    Used by the UI to show why a backend was chosen.
    """
    lower = prompt.lower()
    backend = route(prompt, available_backends)

    reason = "default fallback"

    if is_protocol_concept_query(prompt) or any(kw in lower for kw in _URUK_KEYWORDS):
        reason = "抽象/協議概念或 Uruk/Trinity 關鍵詞 → 需要 URUK 協議載體 relay 環境"
    elif any(kw in lower for kw in _CODE_KEYWORDS):
        reason = "代碼任務 → Codex/Desktop；不可用時用本地模型"
    elif any(kw in lower for kw in _WINDOWS_CONTEXT_KEYWORDS):
        reason = "Windows/畫面/文件情境 → Copilot Desktop"
    elif len(prompt) < _SHORT_THRESHOLD:
        reason = f"短查詢 ({len(prompt)} chars) → 快速回應"
    elif len(prompt) >= _LONG_THRESHOLD:
        reason = f"長/複雜查詢 ({len(prompt)} chars) → URUK 協議載體 relay 深度分析"
    elif any(kw in lower for kw in _DEEP_KEYWORDS):
        reason = "分析類關鍵詞 → 深度推理"

    return {
        "backend":  backend.value,
        "reason":   reason,
        "prompt_len": len(prompt),
        "available": available_backends,
    }
