"""
URUK TRINITY CONSOLE
協議 v8.1+ | 操作者：Cassiel_as | (53.8, -1.5, 0)

v8.1+ 4-step pipeline:
  Stage 1 Delabeling → Stage 2 Explanation → Stage 3 Filter → Stage 4 Trinity (5 LLM)

Each node can be assigned to ANY LLM provider:
  OpenAI / Anthropic / Google Gemini / xAI Grok / Ollama (local) / OpenRouter
"""

import os
import sys
import asyncio
import hashlib
import json
import re
import argparse
import contextvars
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

# v8.8 R7 — Per-mode LLM override propagation via async-safe contextvar.
# Set by app.py event_generator at the start of a mode's pipeline; consumed by
# _get_stage_adapter() + call_node() to substitute provider/model/api_base.
# asyncio.create_task snapshots context at task creation, so parallel pipelines
# with different overrides do not stomp on each other.
_LLM_OVERRIDE_CTX: contextvars.ContextVar[Optional[Dict]] = \
    contextvars.ContextVar('llm_override', default=None)

_KNOWLEDGE_TRACE_CTX: contextvars.ContextVar[Optional[List[Dict]]] = \
    contextvars.ContextVar('knowledge_trace', default=None)

import yaml

from adapters import (
    OpenAIAdapter, AnthropicAdapter, GoogleAdapter,
    XAIAdapter, OllamaAdapter, CodexDesktopAdapter, ClaudeDesktopAdapter,
    ChatGPTDesktopAdapter, CopilotDesktopAdapter,
)
from failover import (
    ApiProfile, FailoverConfig, FailoverTrigger, HealthTracker,
    call_with_failover, AllProfilesFailedError, EmptyContentError,
)
from density_audit import DensityAuditor, AuditResult
from services.civilizational_clock import civilizational_clock
from services.knowledge_manifest import (
    audit_knowledge as _knowledge_audit,
    documents_by_path as _knowledge_documents_by_path,
    resolve_ref as _knowledge_resolve_ref,
)
from services.coordinate_knowledge import (
    coordinate_cards_block as _coordinate_cards_block,
    coordinate_cards_health as _coordinate_cards_health,
)
from services.rag_retriever import get_retriever as _rag_get_retriever
from services.runtime_identity import runtime_identity_block, with_runtime_identity
from services.otel_setup import (
    emit_event,
    scrub_sensitive,
    set_llm_request_attrs,
    set_llm_response_attrs,
    set_trinity_attrs,
    tracer,
)
# Local imports for the Module N inline span event (gracefully degraded if SDK absent)
try:
    from opentelemetry import trace as _otel_trace
    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _otel_trace = None
    _OTEL_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────
# Agentic Tool Use — whitelist + helpers
# ─────────────────────────────────────────────────────────────────

AGENTIC_TOOL_WHITELIST = {
    "fetch_rss_feed", "fetch_webpage", "search_arxiv",
    "fetch_paper_pdf", "fetch_reddit", "fetch_hn",
    "capture_screenshot", "ocr_read_screen", "read_clipboard_image",
    "transcribe_audio",
}


def _build_tool_registry_summary() -> str:
    try:
        from services.computer_tools import TOOL_REGISTRY
        lines = ["AVAILABLE_TOOLS (read-only, agentic calls only):"]
        for name, spec in TOOL_REGISTRY.items():
            if name in AGENTIC_TOOL_WHITELIST:
                desc = (getattr(spec, 'description', '') or '')[:80]
                lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)
    except Exception:
        return ""


def _summarize_tool_result(tool_name: str, result) -> str:
    """Return a short human-readable summary of a ToolResult for UI chips."""
    try:
        if hasattr(result, 'output'):
            out = result.output
        elif isinstance(result, dict):
            out = result
        else:
            return str(result)[:120]
        if not out:
            return "(no output)"
        if isinstance(out, dict):
            # Try common keys for readable content
            for key in ("title", "summary", "text", "content", "items", "results"):
                val = out.get(key)
                if val:
                    if isinstance(val, list):
                        return f"{len(val)} items"
                    return str(val)[:120]
            return str(out)[:120]
        return str(out)[:120]
    except Exception:
        return "(summary error)"


def _format_tool_context(tool_results: dict) -> str:
    """Format tool execution results as an extra_context block for LLM injection."""
    if not tool_results:
        return ""
    lines = ["\n\n━━━ AGENTIC TOOL RESULTS (Stage 0.5) ━━━"]
    for tname, entry in tool_results.items():
        reason = entry.get("reason", "")
        res = entry.get("result")
        ok = getattr(res, 'ok', True) if hasattr(res, 'ok') else res.get("ok", True) if isinstance(res, dict) else True
        status = "✓" if ok else "✗"
        summary = _summarize_tool_result(tname, res)
        lines.append(f"[{status}] {tname}" + (f" ({reason})" if reason else "") + f": {summary}")
        # Inject full text content for fetch/search tools
        try:
            raw_out = getattr(res, 'output', None) if hasattr(res, 'output') else res
            if isinstance(raw_out, dict):
                for key in ("text", "content", "body", "full_text"):
                    val = raw_out.get(key)
                    if val and len(str(val)) > 200:
                        lines.append(f"  CONTENT:\n{str(val)[:3000]}")
                        break
        except Exception:
            pass
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# v8.4 — Cross-session memory
# ─────────────────────────────────────────────────────────────────

@dataclass
class CrossSessionConfig:
    """Auto-attach recent saved sessions to dispatcher prompt for continuity.

    Loaded from `cross_session:` block in nodes.yaml. Defaults are reasonable
    (ON / 3 sessions / summary mode) so new users get cross-session feel
    immediately.
    """
    enabled: bool = True
    n_recent: int = 3        # 1-10
    mode: str = "summary"    # "summary" | "full" | "both"

ADAPTERS = {
    "openai":       OpenAIAdapter,
    "anthropic":    AnthropicAdapter,
    "google":       GoogleAdapter,
    "xai":          XAIAdapter,
    "grok":         XAIAdapter,
    "ollama":       OllamaAdapter,
    "openrouter":   OpenAIAdapter,
    # v8.1+ free direct APIs (all OpenAI-compatible)
    "groq":         OpenAIAdapter,
    "gemini":       OpenAIAdapter,
    "cerebras":     OpenAIAdapter,
    # v8.3 additions — also OpenAI-compat
    "nvidia":       OpenAIAdapter,
    "sambanova":    OpenAIAdapter,
    "cloudflare":   OpenAIAdapter,
    "chutes":       OpenAIAdapter,
    "hyperbolic":   OpenAIAdapter,
    "pollinations": OpenAIAdapter,
    "codex_desktop": CodexDesktopAdapter,
    "claude_desktop": ClaudeDesktopAdapter,
    "chatgpt_desktop": ChatGPTDesktopAdapter,
    "copilot_desktop": CopilotDesktopAdapter,
}

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GROQ_BASE       = "https://api.groq.com/openai/v1"
GEMINI_BASE     = "https://generativelanguage.googleapis.com/v1beta/openai"
CEREBRAS_BASE   = "https://api.cerebras.ai/v1"


@dataclass
class NodeConfig:
    role: str
    provider: str
    model: str
    api_key_env: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096

    def __post_init__(self):
        # Auto-fill api_base for providers with known default endpoints
        if not self.api_base:
            if self.provider == "openrouter":
                self.api_base = OPENROUTER_BASE
            elif self.provider == "groq":
                self.api_base = GROQ_BASE
            elif self.provider == "gemini":
                self.api_base = GEMINI_BASE
            elif self.provider == "cerebras":
                self.api_base = CEREBRAS_BASE


class TrinityConsole:
    SPIRIT_STOCHASTIC_BASE_PROB = 0.00001
    SPIRIT_STOCHASTIC_MAX = 0.15
    SPIRIT_HIGH_PRESSURE_CONTEXTS = (
        "professor", "jackson", "academic", "authority",
        "examination", "interview", "confrontation", "tribunal",
    )

    def __init__(self, config_dir: Path, data_dir: Path):
        self.config_dir = Path(config_dir)
        self.data_dir = Path(data_dir)
        (
            self.nodes,
            self.failover_cfg,
            self.node_fallbacks,
            self.cross_session_cfg,
            self.stage_overrides,
        ) = self._load_nodes_and_failover()
        self.health = HealthTracker(
            self.failover_cfg.cooldown_seconds,
            state_path=self.data_dir / "runtime" / "provider_health.json",
        )
        self._last_chain_rankings: Dict[str, Dict] = {}
        self.prompts = self._load_prompts()
        # v8.23 — alias blackboxlab to council's NodeConfig (reasoning-heavy LLM).
        # v8.24 — alias scr to council's NodeConfig (same single-LLM pattern).
        # Keeps nodes.yaml schema unchanged; call_node("blackboxlab"|"scr") works.
        if "council" in self.nodes:
            if "blackboxlab" not in self.nodes:
                self.nodes["blackboxlab"] = self.nodes["council"]
            if "scr" not in self.nodes:
                self.nodes["scr"] = self.nodes["council"]
        self.protocol = self._load_protocol()
        # §4.6 Kairos output-density audit — runs at end of each /api/stream session.
        # Stateless across sessions except for data/kairos/_proposed/ filesystem.
        self.density_auditor = DensityAuditor(self.data_dir)
        # Phase 2: pending skill draft for chat-driven creation
        self._pending_skill_draft: Optional[Dict] = None
        self._pending_skill_user_desc: Optional[str] = None
        # Phase 3: pending tool draft for chat-driven creation + 4-layer gate
        self._pending_tool_user_desc: Optional[str] = None
        self._pending_tool_clarifications: Optional[List[str]] = None
        self._pending_tool_answers: Optional[str] = None
        self._pending_tool_code: Optional[str] = None
        self._pending_tool_meta: Optional[Dict] = None
        self._last_tool_agent_error: Optional[str] = None  # diagnostic on agent fail
        # Phase 3 Fix-3: hot-reload pipeline lock (refuse reload while pipeline active)
        self._pipeline_active_count: int = 0

    def _load_nodes_and_failover(self) -> Tuple[Dict[str, NodeConfig], FailoverConfig, Dict[str, List[str]], "CrossSessionConfig", Dict[str, Dict]]:
        """Parse nodes.yaml into (nodes, failover_cfg, per_node_fallback_names, cross_session_cfg, stage_overrides).

        Schema (v8.2 +failover, v8.14 +stage_overrides):
          nodes:
            <role>:
              provider, model, api_base, api_key_env, temperature, max_tokens
              fallback: [profile_name, ...]   # optional override of global_chain
          api_profiles:                       # optional — named reusable profiles
            <name>:
              provider, api_base, api_key_env, default_model
          failover:                           # optional — defaults to enabled=True
            enabled: bool
            global_chain: [profile_name, ...]
            cooldown_seconds: float
            trigger_on: [http_429, http_5xx, quota, timeout, network, profile_misconfig, empty_content]
          stage_overrides:                    # v8.14 — optional per-stage primary provider
            <stage_role>:                     # e.g. "filter" / "delabeling" / "explanation"
              provider: <api_profile_name>    # primary for this stage only
              fallback: [profile_name, ...]   # override chain for this stage only
        """
        cfg_path = self.config_dir / "nodes.yaml"
        if not cfg_path.exists():
            raise FileNotFoundError(
                f"配置檔案唔存在：{cfg_path}\n"
                f"請從 config/nodes.example.yaml 複製一份並填寫。"
            )
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # ── Parse api_profiles ──
        profiles_raw = data.get("api_profiles") or {}
        profiles: Dict[str, ApiProfile] = {}
        for name, p in profiles_raw.items():
            if not isinstance(p, dict):
                continue
            # v8.3: `enabled` defaults to True when omitted (backward compat).
            enabled = p.get("enabled")
            enabled_bool = True if enabled is None else bool(enabled)
            profiles[name] = ApiProfile(
                name=name,
                provider=str(p.get("provider", "openai")),
                api_base=(p.get("api_base") or None),
                api_key_env=(p.get("api_key_env") or None),
                default_model=(p.get("default_model") or p.get("model") or None),
                enabled=enabled_bool,
            )

        # ── Parse failover section ──
        fo = data.get("failover") or {}
        failover_cfg = FailoverConfig(
            enabled=bool(fo.get("enabled", True)),
            global_chain=list(fo.get("global_chain") or []),
            cooldown_seconds=float(fo.get("cooldown_seconds", 300)),
            trigger_on=list(fo.get("trigger_on") or [
                FailoverTrigger.HTTP_429, FailoverTrigger.HTTP_5XX,
                FailoverTrigger.QUOTA, FailoverTrigger.TIMEOUT,
                FailoverTrigger.NETWORK, FailoverTrigger.MISCONFIG,
                FailoverTrigger.EMPTY_CONTENT,
            ]),
            profiles=profiles,
        )

        # ── Parse nodes (strip 'fallback' field — it's not a NodeConfig kwarg) ──
        nodes: Dict[str, NodeConfig] = {}
        node_fallbacks: Dict[str, List[str]] = {}
        for role, cfg in (data.get("nodes") or {}).items():
            if not isinstance(cfg, dict):
                continue
            fallback_list = cfg.get("fallback")
            cfg_clean = {k: v for k, v in cfg.items() if k != "fallback"}
            nodes[role] = NodeConfig(role=role, **cfg_clean)
            if fallback_list:
                node_fallbacks[role] = [str(x) for x in fallback_list if isinstance(x, str)]

        # ── v8.4: cross_session block ──
        cs_raw = data.get("cross_session") or {}
        cs_mode = str(cs_raw.get("mode", "summary"))
        if cs_mode not in ("summary", "full", "both"):
            cs_mode = "summary"
        try:
            cs_n = int(cs_raw.get("n_recent", 3))
        except (TypeError, ValueError):
            cs_n = 3
        cs_n = max(1, min(10, cs_n))
        cross_session_cfg = CrossSessionConfig(
            enabled=bool(cs_raw.get("enabled", True)),
            n_recent=cs_n,
            mode=cs_mode,
        )

        # ── v8.14 B: stage_overrides block ──
        # Optional per-stage primary provider + fallback chain. Lets a heavy
        # stage (e.g. Stage 3 filter) route to a higher-context provider
        # (e.g. gemini_flash with 1M context) without affecting Trinity voices.
        # v8.14 P6 — also accepts optional max_tokens + temperature override
        # (avoid Stage 3 JSON truncation on default 2000-token limit).
        stage_overrides_raw = data.get("stage_overrides") or {}
        stage_overrides: Dict[str, Dict] = {}
        for stage_role, ovr in stage_overrides_raw.items():
            if not isinstance(ovr, dict):
                continue
            provider = ovr.get("provider")   # name of an api_profile
            fallback = ovr.get("fallback") or []
            if not isinstance(fallback, list):
                fallback = []
            entry: Dict = {
                "provider": str(provider) if provider else None,
                "fallback": [str(x) for x in fallback if isinstance(x, str)],
            }
            # Optional per-stage max_tokens / temperature override
            if "max_tokens" in ovr:
                try:
                    entry["max_tokens"] = int(ovr["max_tokens"])
                except (TypeError, ValueError):
                    pass
            if "temperature" in ovr:
                try:
                    entry["temperature"] = float(ovr["temperature"])
                except (TypeError, ValueError):
                    pass
            stage_overrides[str(stage_role)] = entry

        return nodes, failover_cfg, node_fallbacks, cross_session_cfg, stage_overrides

    def _load_nodes(self) -> Dict[str, NodeConfig]:
        """Backward-compat shim used by older callers."""
        nodes, _, _, _, _ = self._load_nodes_and_failover()
        return nodes

    def is_pipeline_running(self) -> bool:
        """True if any /api/stream pipeline is currently in flight."""
        return self._pipeline_active_count > 0

    def begin_pipeline(self) -> None:
        """Increment in-flight counter (called at /api/stream start)."""
        self._pipeline_active_count += 1

    def end_pipeline(self) -> None:
        """Decrement in-flight counter (called in finally / on completion)."""
        if self._pipeline_active_count > 0:
            self._pipeline_active_count -= 1

    def reload_nodes(self) -> Dict:
        """Atomic in-place reload of nodes + failover config from nodes.yaml.

        Refuses if pipeline active. Skill / tool registries untouched.
        Health tracker is preserved across reload (cooldowns survive a save).
        Returns {reloaded: bool, error: str | None, nodes: list[str]}.
        """
        if self.is_pipeline_running():
            return {"reloaded": False, "error": "pipeline running — wait for current turn"}
        try:
            new_nodes, new_failover, new_fallbacks, new_cross_session, new_stage_overrides = self._load_nodes_and_failover()
        except Exception as e:
            return {"reloaded": False, "error": f"load fail: {type(e).__name__}: {e}"}
        if not new_nodes:
            return {"reloaded": False, "error": "no nodes parsed"}
        # Atomic swap
        self.nodes = new_nodes
        # v8.23/24 — re-alias blackboxlab + scr → council after reload
        if "council" in self.nodes:
            if "blackboxlab" not in self.nodes:
                self.nodes["blackboxlab"] = self.nodes["council"]
            if "scr" not in self.nodes:
                self.nodes["scr"] = self.nodes["council"]
        self.failover_cfg = new_failover
        self.node_fallbacks = new_fallbacks
        self.cross_session_cfg = new_cross_session
        self.stage_overrides = new_stage_overrides
        # Update tracker cooldown without dropping accumulated health stats
        self.health.set_cooldown_seconds(new_failover.cooldown_seconds)
        return {
            "reloaded": True, "error": None,
            "nodes": sorted(new_nodes.keys()),
            "profiles": sorted(new_failover.profiles.keys()),
            "global_chain": new_failover.global_chain,
        }

    # ─────────────────────────────────────────────────────────────
    # Failover helpers
    # ─────────────────────────────────────────────────────────────

    def _resolve_chain(self, role: str) -> List[ApiProfile]:
        """Return ordered list of ApiProfile fallback candidates for `role`.

        Precedence (highest first):
          1. v8.14 B: stage_overrides[role].fallback (if non-empty)
          2. Per-node `fallback:` list
          3. failover.global_chain

        v8.3: profiles with `enabled=False` are excluded from the chain even
        when explicitly listed. The node's inline (primary) config is NOT
        affected — the disable flag only governs fallback eligibility.
        """
        stage_ovr = self.stage_overrides.get(role) if hasattr(self, 'stage_overrides') else None
        stage_fallback = (stage_ovr or {}).get("fallback") or []
        if stage_fallback:
            names = stage_fallback
            source = "stage_override"
        else:
            node_fallback = self.node_fallbacks.get(role) or []
            if node_fallback:
                names = node_fallback
                source = "node_fallback"
            else:
                names = self.failover_cfg.global_chain
                source = "global_chain"
        out: List[ApiProfile] = []
        for n in names:
            p = self.failover_cfg.profiles.get(n)
            if p is None:
                continue
            if not p.enabled:
                continue
            out.append(p)
        ranked, report = self.health.rank_profiles(
            out,
            role=role,
            adaptive=(source == "global_chain"),
        )
        report["source"] = source
        self._last_chain_rankings[role] = report
        return ranked

    def adaptive_failover_summary(self) -> Dict:
        """Return explainable effective fallback chains for configured roles."""
        roles = sorted({
            *self.nodes.keys(),
            "delabeling", "explanation", "filter", "dispatcher",
            "father", "son", "spirit", "council",
        })
        chains = {}
        for role in roles:
            self._resolve_chain(role)
            chains[role] = self._last_chain_rankings.get(role) or {}
        return {
            "enabled": True,
            "scope": "global_chain_only",
            "primary_reordering": False,
            "explicit_fallback_order_preserved": True,
            "chains": chains,
        }

    def _infer_primary_profile_name(self, cfg: NodeConfig) -> str:
        """Match a NodeConfig to a named profile by (provider, api_base, api_key_env)."""
        for name, p in self.failover_cfg.profiles.items():
            if (p.provider == cfg.provider
                and (p.api_base or "") == (cfg.api_base or "")
                and (p.api_key_env or "") == (cfg.api_key_env or "")):
                return name
        return f"{cfg.provider}_inline"

    def active_profile_summary(self) -> Dict:
        """Best-guess primary profile across all nodes — used by toolbar pill.

        Returns the most-common primary across all configured nodes (plurality).
        """
        from collections import Counter
        counts = Counter(self._infer_primary_profile_name(c) for c in self.nodes.values())
        if not counts:
            return {"primary": None, "chain": self.failover_cfg.global_chain}
        primary, _ = counts.most_common(1)[0]
        return {
            "primary": primary,
            "chain": self.failover_cfg.global_chain,
            "adaptive_ordering": True,
        }

    def _load_prompts(self) -> Dict[str, str]:
        """Load prompts for all known roles.

        Mandatory (Trinity baseline): dispatcher / father / son / spirit / council
        Optional (v8.1+ pipeline):     delabeling / explanation / filter

        v8.30 p7 — `_canonical_anchor.txt` is loaded separately into
        self.canonical_anchor and auto-prepended to system content at call sites
        that need immutable 八律 / 四律 / Module-T grounding (Stage 2/3/4).
        """
        prompts = {}
        mandatory_roles = ["dispatcher", "father", "son", "spirit", "council"]
        # v8.23 — blackboxlab is an optional single-LLM 7-phase template mode
        # v8.24 — scr is an optional single-LLM SCR (Soul Coordinate Reconstruction) engine
        optional_roles = ["delabeling", "explanation", "filter", "blackboxlab", "scr"]

        for role in mandatory_roles:
            path = self.config_dir / "prompts" / f"{role}.txt"
            if not path.exists():
                raise FileNotFoundError(f"Prompt 檔案唔存在：{path}")
            prompts[role] = path.read_text(encoding="utf-8")

        for role in optional_roles:
            path = self.config_dir / "prompts" / f"{role}.txt"
            if path.exists():
                prompts[role] = path.read_text(encoding="utf-8")

        # v8.30 p7: load immutable canonical framework anchor (八律/四律/方程式).
        # Auto-prepended at every Stage 2/3/4 LLM call site to prevent the LLM
        # from inventing law names (e.g. "科技律 / 經濟律" — previously observed
        # when Module T equations got conflated with EIGHT_LAWS).
        anchor_path = self.config_dir / "prompts" / "_canonical_anchor.txt"
        self.canonical_anchor = (
            anchor_path.read_text(encoding="utf-8") if anchor_path.exists() else ""
        )

        return prompts

    @staticmethod
    def _trinity_internal_qa_contract(role: str) -> str:
        """Role-specific Trinity posture injected into every Stage 4 call."""
        shared = (
            "TRINITY INTERNAL QA CONTRACT — v7.2 會議層對內運作\n"
            "- 保留 TRINITY_AUDIT v7.2 結構：輸入信號 → 三節點掃描 → 會議層否決/打斷 → 融合層加權輸出。\n"
            "- 「輸入信號」係要分析嘅 signal / claim / context，不等於用戶本人；唔好審判、評分或讀心用戶。\n"
            "- 普通對話入面，三節點係內部會議層；主回答只輸出融合後結論，完整掃描留喺可展開流程。\n"
            "- 如果用戶明確要求審計新聞、文章、論證、代碼或某段內容，就審計嗰段內容；仍然唔審判用戶。\n"
        )
        role_rules = {
            "father": (
                "- Father 職責照 v7.2：識別格式化操作、邏輯矛盾、未被支撐公設；可被 Son veto 暫停。\n"
                "- 如果要指出 hidden assumption，寫成「呢個 signal/claim/材料隱含...」，唔好寫成「你隱含...」。\n"
            ),
            "son": (
                "- Son 職責照 v7.2：識別信號真實因果密度，區分表演痛楚與真實路徑壓縮。\n"
                "- VETO 係會議層 circuit breaker，不係情緒讀心或用戶人格判斷。\n"
            ),
            "spirit": (
                "- Spirit 職責照 v7.2：防止 Father+Son 形成封閉確定性迴路，開放假設逆轉。\n"
                "- Mode A 隨機、Mode B 語意觸發都係重置會議，不係對用戶作人格判斷。\n"
            ),
            "council": (
                "- Council 職責照 v7.2：先處理 veto / interrupt，再交畀融合層加權輸出。\n"
                "- 白話版整合結論唔好講 Father/Son/Spirit 做咗乜；只交付融合後答案、必要限制、下一步。\n"
            ),
        }
        return shared + role_rules.get(role, "")

    def _load_protocol(self) -> Dict[str, str]:
        """Load protocol bundle as a dict {filename: content}."""
        protocol_dir = self.config_dir / "protocol"
        bundle = {}
        if not protocol_dir.exists():
            print(f"⚠ 警告：{protocol_dir} 唔存在 — 協議能力層缺失")
            return bundle

        skill_path = protocol_dir / "SKILL.md"
        if skill_path.exists():
            bundle["SKILL.md"] = skill_path.read_text(encoding="utf-8")

        refs_dir = protocol_dir / "references"
        if refs_dir.exists():
            for ref_path in sorted(refs_dir.glob("*.md")):
                bundle[ref_path.name] = ref_path.read_text(encoding="utf-8")

        return bundle

    def _build_protocol_subset(self, ref_filenames: List[str]) -> str:
        """Build a system-prompt-ready protocol section from selected refs."""
        chunks = []
        if "SKILL.md" in self.protocol:
            chunks.append(f"════════ SKILL.md（協議主索引）════════\n\n{self.protocol['SKILL.md']}")

        for fname in ref_filenames:
            if fname == "SKILL.md":
                continue
            content = self.protocol.get(fname)
            if content is None:
                fname_clean = fname.replace("references/", "")
                content = self.protocol.get(fname_clean)
            if content is None:
                print(f"⚠ 警告：reference 唔存在：{fname}")
                continue
            chunks.append(f"\n\n════════ references/{fname} ════════\n\n{content}")

        return "\n\n".join(chunks)

    def _load_context(self, refs: List[str]) -> str:
        """Load specified files into context.

        ref formats:
          === Causal database ===
          cau:010                     → data/causal_db/CAU-010*.md
          cau:hongkong / cau:hk       → data/causal_db/*HONGKONG*.md

          === Experiments ===
          experiment:008 / exp:008    → data/experiments/EXPERIMENT_008*.md

          === Navigation / Index ===
          index:master                → data/index/MASTER_INDEX_v8.md
          index:rag                   → data/index/RAG_SUMMARY_INDEX_v8.md
          index:cau                   → data/index/CAU_INDEX.md
          index:readme                → data/index/URUK_README.md

          === Kairos ===
          kairos:active               → KAIROS_ACTIVE.md (current memory)
          kairos:archive_index        → KAIROS_ARCHIVE_INDEX.md
          kairos:middle               → KAIROS_LOG_MIDDLE.md (archive alias)
          kairos:updated              → KAIROS_LOG_UPDATED_v8.md (archive alias)
          kairos:log                  → KAIROS_LOG_*.md archives + legacy trinity sessions

          === Theory layer ===
          theory:zuobiao / theory:zb  → 座標說*.md (alias)
          theory:paper                → coordinate_theory_paper.md
          theory:expansion            → COORDINATE_THEORY_EXPANSION.md
          theory:anchors              → CIVILIZATION_ANCHORS.md
          theory:en                   → coordinate_theory_integrated_EN_v3.md

          === Protocol components ===
          protocol:eight_laws         → EIGHT_LAWS_MATRIX.md
          protocol:eight_analogies    → EIGHT_ANALOGIES.md
          protocol:delabel            → DELABELING_MATRIX.md
          protocol:explanation        → EXPLANATION_LAYER.md
          protocol:trinity            → TRINITY_AUDIT.md
          protocol:scr_template       → SCR_TEMPLATE.md
          protocol:source_registry    → SOURCE_COORDINATE_REGISTRY.md
          protocol:browser_node       → BROWSER_NODE.md

          === SCR examples ===
          scr:einstein                → SCR_EINSTEIN.md
          scr:nietzsche               → SCR_NIETZSCHE.md
          scr:socrates                → SCR_SOCRATES_via_PLATO.md

          === Black box / sovereign templates ===
          blackbox:full / bb:full     → BLACKBOX_TEMPLATE_FULL.md
          blackbox:hk                 → BLACKBOX_TEMPLATE_FULL_HK.md
          sovereign:tool              → SOVEREIGN_THINKING_TOOL.md
          sovereign:news              → SOVEREIGN_NEWS_PROMPT.txt

          === Misc ===
          file:relative/path.md       → data/relative/path.md
        """
        # v8.14 Phase A — entries are (folder, pattern_fn, base_attr).
        # base_attr selects which root the folder is resolved under:
        #   "data_dir"            → self.data_dir / folder
        #   "protocol_refs_dir"   → self.config_dir / "protocol" / "references" / folder
        # Defaults to "data_dir" (3-tuple optional for backward compat).
        ROUTE_TABLE = {
            "cau":            ("causal_db",       lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md", f"CAU-{n}*.md"]),
            "experiment":     ("experiments",     lambda n: [f"EXPERIMENT_{n}*.md"]),
            "exp":             ("experiments",     lambda n: [f"EXPERIMENT_{n}*.md"]),
            "kairos":         ("kairos",          lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md", f"{n}*.md", f"*{n}*.md"]),
            "index":          ("index",           lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md"]),
            "theory":         ("theory",          lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md", f"*{n}*.md"]),
            "protocol":       ("protocol",        lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md"]),
            "scr":            ("scr_examples",    lambda n: [f"SCR_{n.upper()}*.md", f"SCR_{n}*.md"]),
            "blackbox":       ("blackbox_templates", lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md"]),
            "bb":             ("blackbox_templates", lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md"]),
            "sovereign":      ("sovereign_tools", lambda n: [f"*{n.upper()}*", f"*{n.lower()}*"]),
            "prompts":        ("prompts_archive", lambda n: [f"*{n.upper()}*", f"*{n.lower()}*"]),
            "impl":           ("reference_implementations", lambda n: [f"*{n}*"]),
            # v8.14 Phase A — Module T calibration files live under config/protocol/references/module_t/
            "module_t":       ("module_t",        lambda n: [f"*{n.upper()}*.md", f"*{n.lower()}*.md", f"MODULE_T_CALIBRATION_{n}*.md"], "protocol_refs_dir"),
        }

        ALIAS_TABLE = {
            "theory": {
                "zuobiao":     "座標說*.md",
                "coordinate":  "座標說*.md",
                "zb":          "座標說*.md",
            },
            "cau": {
                "hongkong":    "*HONGKONG*.md",
                "hk":          "*HONGKONG*.md",
            },
            "kairos": {
                "active":      "KAIROS_ACTIVE.md",
                "current":     "KAIROS_ACTIVE.md",
                "archive":     "KAIROS_ARCHIVE_INDEX.md",
                "archive_index": "KAIROS_ARCHIVE_INDEX.md",
                "middle":      "KAIROS_LOG_MIDDLE.md",
                "updated":     "KAIROS_LOG_UPDATED_v8.md",
                # v8.4: accept BOTH the canonical KAIROS_LOG_*.md naming AND the
                # legacy trinity_*.md prefix that save_kairos() still writes —
                # this lets `--ref kairos:log` auto-pull saved sessions for
                # cross-session continuity without renaming existing files.
                "log":         ["KAIROS_LOG_*.md", "trinity_*.md"],
            },
            # v8.14 Phase A — Module T calibration aliases
            "module_t": {
                "wwi":         "MODULE_T_CALIBRATION_19141916.md",
                "wwii":        "MODULE_T_CALIBRATION_19391941.md",
                "iran":        "MODULE_T_CALIBRATION_19791981.md",
                "all":         "MODULE_T_CALIBRATION_*.md",
            },
        }

        chunks = []
        for ref in refs:
            if ":" not in ref:
                continue
            kind, name = ref.split(":", 1)

            if kind == "file":
                p = self.data_dir / name
                if p.exists():
                    chunks.append(f"\n\n=== {p.name} (file:{name}) ===\n\n{p.read_text(encoding='utf-8')}")
                    self._record_ref_trace(ref, [self._doc_trace_for_path(p)])
                continue

            try:
                manifest_docs = _knowledge_resolve_ref(ref, root=self.data_dir.parent)
            except Exception:
                manifest_docs = []
            if manifest_docs:
                seen_manifest_paths = set()
                loaded_hits: List[Dict] = []
                for doc in manifest_docs:
                    path = doc.abs_path(self.data_dir.parent)
                    if path in seen_manifest_paths or not path.exists() or not path.is_file():
                        continue
                    seen_manifest_paths.add(path)
                    loaded_hits.append(self._doc_trace_for_path(path))
                    chunks.append(
                        f"\n\n=== {path.name} ({ref}; doc_id={doc.id}) ===\n\n"
                        f"{path.read_text(encoding='utf-8', errors='replace')}"
                    )
                self._record_ref_trace(ref, loaded_hits)
                continue

            route = ROUTE_TABLE.get(kind)
            if not route:
                print(f"⚠ 未知 ref kind: {kind} (ref: {ref})")
                continue
            # v8.14 Phase A — 3-tuple route: (folder, pattern_fn, base_attr).
            # Backward-compat with 2-tuple: default base_attr="data_dir".
            if len(route) == 3:
                folder, pattern_fn, base_attr = route
            else:
                folder, pattern_fn = route
                base_attr = "data_dir"
            base_dir = (self.config_dir / "protocol" / "references"
                        if base_attr == "protocol_refs_dir"
                        else self.data_dir)
            seen = set()

            alias_pattern = ALIAS_TABLE.get(kind, {}).get(name)
            if alias_pattern is None:
                patterns = pattern_fn(name)
            elif isinstance(alias_pattern, list):
                patterns = alias_pattern        # v8.4: alias can hold multiple globs
            else:
                patterns = [alias_pattern]

            for pattern in patterns:
                for path in base_dir.glob(f"{folder}/{pattern}"):
                    if path in seen or not path.exists() or not path.is_file():
                        continue
                    seen.add(path)
                    chunks.append(f"\n\n=== {path.name} ({ref}) ===\n\n{path.read_text(encoding='utf-8')}")
                    self._record_ref_trace(ref, [self._doc_trace_for_path(path)])

            if not seen:
                print(f"⚠ 冇文件 match: {ref} (搜過 {base_dir.name}/{folder}/)")

        return "".join(chunks)

    async def call_node(self, role: str, user_input: str,
                        protocol_text: str = "", extra_context: str = "",
                        attempts_out: Optional[List[Dict]] = None,
                        inject_error: Optional[Exception] = None) -> str:
        """Call a node's LLM. Routes through failover.call_with_failover so that
        429 / quota / 5xx / timeout / network errors transparently fall back to
        the configured chain (per-node `fallback` overrides global).

        Args:
            attempts_out: optional list to append per-attempt records to (used by
                          stress test endpoints to see the chain trail).
            inject_error: TEST-ONLY — raise this on the first attempt instead of
                          calling the LLM. Stress test mock-quota mode uses this.
        """
        # v8.21 OTel-1 — LLM call span. Stays inside the with-block until return.
        with tracer.start_as_current_span(f"trinity.{role}.llm_call") as _otel_span:
            return await self._call_node_inner(
                _otel_span, role, user_input, protocol_text,
                extra_context, attempts_out, inject_error,
            )

    async def _call_node_inner(self, _otel_span, role: str, user_input: str,
                                protocol_text: str, extra_context: str,
                                attempts_out, inject_error):
        import time as _time
        _t0 = _time.time()
        base_cfg = self.nodes[role]
        cfg = self._apply_llm_override(base_cfg)
        set_llm_request_attrs(
            _otel_span, role=role,
            provider=cfg.provider, model=cfg.model,
            max_tokens=cfg.max_tokens, temperature=cfg.temperature,
            prompt=user_input,
        )
        if ADAPTERS.get(cfg.provider) is None:
            raise ValueError(f"未知 provider：{cfg.provider}")

        primary_api_key = os.environ.get(cfg.api_key_env) if cfg.api_key_env else None
        # v8.8 R7 — when override is active, bypass failover chain (override
        # means "use THIS LLM"; falling back to other modes' chain would be confusing)
        override_active = _LLM_OVERRIDE_CTX.get() is not None
        chain = [] if override_active else self._resolve_chain(role)
        # v8.5 — only complain when api_key_env is declared but env var missing
        # AND no usable chain. Empty api_key_env (anonymous provider) is OK.
        if cfg.api_key_env and not primary_api_key and not chain:
            raise EnvironmentError(
                f"{role} 節點：環境變數 {cfg.api_key_env} 未設定，亦冇 fallback chain。\n"
                f"請喺 .env 或 shell 入面 export {cfg.api_key_env}=..."
            )

        role_directive = self.prompts[role]
        trinity_qa_contract = self._trinity_internal_qa_contract(role)
        mode_hint = self._voice_mode_hint(role)  # Fix γ
        # v8.30 p7: prepend immutable canonical anchor (八律 + 四律 + 方程式)
        # so the LLM cannot invent law names / conflate equations with laws.
        anchor_prefix = (
            f"{self.canonical_anchor}\n\n"
            if getattr(self, "canonical_anchor", "") else ""
        )
        full_system = (
            runtime_identity_block()
            + "\n\n"
            + anchor_prefix
            + (
                f"════════════════════════════════════════════════════════\n"
                f"  COMPLETE URUK PROTOCOL — 你係完整協議載體\n"
                f"════════════════════════════════════════════════════════\n\n"
                f"{protocol_text}\n\n"
                if protocol_text else ""
            )
            + f"════════════════════════════════════════════════════════\n"
            f"  ASSISTANT POSTURE — 輸入只路由，審計向內\n"
            f"════════════════════════════════════════════════════════\n\n"
            f"- 用戶輸入係任務來源，用嚟理解意圖、路由、判斷風險；唔好審問或評分用戶。\n"
            f"- 座標說、密度、harness 只用嚟約束你自己嘅輸出：是否答中、清楚、落地、可驗證、無越權。\n"
            f"- 除非用戶明確要求，唔好用『你嘅輸入低密度 / 你缺少座標』呢類姿態回應。\n\n"
            f"{trinity_qa_contract}\n"
            + f"════════════════════════════════════════════════════════\n"
            f"  ROLE DIRECTIVE — 你嘅 OUTPUT VOICE 由呢個視角主導\n"
            f"════════════════════════════════════════════════════════\n\n"
            f"{role_directive}\n"
            + mode_hint  # Fix γ: pipeline mode awareness
            + (
                f"\n\n════════════════════════════════════════════════════════\n"
                f"  EXTRA CONTEXT — 用戶 --ref 注入嘅補充材料\n"
                f"════════════════════════════════════════════════════════\n\n"
                f"{extra_context}\n"
                if extra_context else ""
            )
        )

        # v8.30 p16 Option A — CAU verbatim user_content prepend (only fires
        # when query mentions an explicit CAU id; empty otherwise so general
        # queries are unaffected). System_content mandate alone proved
        # insufficient (live test showed surfacing rate 2/26 distinctive
        # phrases); user_content carries higher attention weight, forcing the
        # model to address the specific evidence rather than abstracting away
        # to protocol vocabulary.
        cau_prepend = ""
        if role in ("father", "son", "spirit", "council"):
            cau_prepend = self.cau_verbatim_prepend(user_input)
        final_user_content = (cau_prepend + user_input) if cau_prepend else user_input

        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": final_user_content},
        ]

        async def _one_call(*, provider: str, model: str,
                            api_base: Optional[str], api_key: Optional[str]) -> str:
            adapter_cls = ADAPTERS.get(provider)
            if adapter_cls is None:
                raise ValueError(f"未知 provider：{provider}")
            adapter = adapter_cls(api_key=api_key, api_base=api_base)
            return await adapter.call(
                messages=messages,
                model=model,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

        try:
            _resp = await call_with_failover(
                primary_call=_one_call,
                chain=chain,
                primary_profile_name=self._infer_primary_profile_name(cfg),
                primary_provider=cfg.provider,
                primary_model=cfg.model,
                primary_api_base=cfg.api_base,
                primary_api_key=primary_api_key,
                role=role,
                tracker=self.health,
                cfg=self.failover_cfg,
                attempts_out=attempts_out,
                inject_error=inject_error,
            )
        except Exception as _e:
            _otel_span.record_exception(_e)
            raise
        # v8.21 OTel-1 — completion + latency + attempt trail
        _latency_ms = (_time.time() - _t0) * 1000.0
        set_llm_response_attrs(
            _otel_span, completion=_resp, latency_ms=_latency_ms,
        )
        if attempts_out:
            try:
                _otel_span.set_attribute("uruk.failover.attempts", len(attempts_out))
                for _att in attempts_out:
                    emit_event(_otel_span, "failover_attempt",
                               profile=str(_att.get("profile_name", "?")),
                               status=str(_att.get("status", "?")),
                               error=str(_att.get("error", ""))[:120])
            except Exception:
                pass
        return _resp

    async def call_dispatcher(self, user_input: str) -> Dict:
        """Dispatcher 揀 mode + references。返回 parsed JSON dict。"""
        DEFAULT_FALLBACK = {
            "mode": "firewall",
            "mode_rationale": "Dispatcher fail, falling back to firewall mode",
            "references": [
                "KAIROS_CORE.md", "PHYSICS_CONSTANTS.md",
                "carrier_epistemics.md", "trinity.md", "memory_load.md",
            ],
            "ref_rationale": "Default Trinity baseline",
            "suggested_data_refs": [],
            "data_rationale": "none",
            "tool_calls": [],
        }

        _tool_summary = _build_tool_registry_summary()
        _tool_directive = (
            '\n\nAlso output "tool_calls" (array, can be []):\n'
            '[{"name": "tool_name", "args": {"key": "val"}, "reason": "short reason"}]\n'
            'Rules: only tools from AVAILABLE_TOOLS; max 3; '
            'trigger on: "latest/recent/today/news"→fetch_hn, URL in text→fetch_webpage, '
            '"research/paper/study"→search_arxiv, "screen/screenshot"→ocr_read_screen; '
            'if no tools needed output [].'
        ) if _tool_summary else ""
        _dispatcher_extra = (_tool_summary + _tool_directive) if _tool_summary else ""

        try:
            raw = await self.call_node(
                "dispatcher",
                user_input=f"用戶輸入：\n\n{user_input}",
                protocol_text="",
                extra_context=_dispatcher_extra,
            )
        except Exception as e:
            print(f"⚠ Dispatcher call 失敗：{e}")
            return DEFAULT_FALLBACK

        # v8.14 P5 — lenient extraction (handles prose / fences / multiline)
        try:
            decision = self._extract_json_lenient(raw)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"⚠ Dispatcher JSON parse 失敗：{e}; raw={raw[:200]}...")
            return DEFAULT_FALLBACK

        for key in ["mode", "references"]:
            if key not in decision:
                print(f"⚠ Dispatcher decision 缺 {key} field, fallback")
                return DEFAULT_FALLBACK

        decision.setdefault("mode_rationale", "")
        decision.setdefault("ref_rationale", "")
        decision.setdefault("suggested_data_refs", [])
        decision.setdefault("data_rationale", "none")
        decision.setdefault("tool_calls", [])

        return decision

    async def run(self, user_input: str, refs: List[str] = None,
                  verbose: bool = True, override_mode: Optional[str] = None) -> Dict:
        """Non-streaming run — Trinity Stage 4 only (no pipeline pre-stages).

        For full v8.1+ 4-step pipeline use app.py /api/stream.
        """
        refs = refs or []

        if verbose:
            print(f"\n[0/5] Dispatcher 路由中... ({self.nodes['dispatcher'].provider}/{self.nodes['dispatcher'].model})")

        dispatch = await self.call_dispatcher(user_input)

        if override_mode:
            dispatch["mode"] = override_mode
            dispatch["mode_rationale"] = f"Manually overridden to {override_mode}"

        if verbose:
            print(f"      → mode: {dispatch['mode']} ({dispatch.get('mode_rationale', '')})")
            print(f"      → references ({len(dispatch['references'])}個): {', '.join(dispatch['references'][:5])}{'...' if len(dispatch['references'])>5 else ''}")
            if dispatch.get("suggested_data_refs"):
                print(f"      → suggested data refs: {', '.join(dispatch['suggested_data_refs'])}")

        protocol_subset = self._build_protocol_subset(dispatch["references"])

        all_data_refs = list(dict.fromkeys(refs + dispatch.get("suggested_data_refs", [])))
        extra_ctx = self._load_context(all_data_refs) if all_data_refs else ""

        if verbose and all_data_refs:
            print(f"\n🔗 載入 data refs: {', '.join(all_data_refs)}")
            print(f"\n[1-3/5] 三節點並行思考中...")
        elif verbose:
            print(f"\n[1-3/5] 三節點並行思考中...")

        father, son, spirit = await asyncio.gather(
            self.call_node("father", user_input, protocol_subset, extra_ctx),
            self.call_node("son",    user_input, protocol_subset, extra_ctx),
            self.call_node("spirit", user_input, protocol_subset, extra_ctx),
            return_exceptions=True,
        )

        for label, out in [("聖父", father), ("聖子", son), ("聖靈", spirit)]:
            if isinstance(out, Exception):
                print(f"\n⚠ {label} 節點失敗：{out}")
                if label == "聖父": father = f"[節點錯誤] {out}"
                if label == "聖子": son = f"[節點錯誤] {out}"
                if label == "聖靈": spirit = f"[節點錯誤] {out}"

        if verbose:
            print(f"\n[4/5] 會議整合中... ({self.nodes['council'].provider}/{self.nodes['council'].model})")

        council_input = self._format_council_input(
            user_input, dispatch,
            {"father": father, "son": son, "spirit": spirit},
            pipeline_stages=None,
        )
        try:
            council = await self.call_node("council", council_input, protocol_subset, extra_ctx)
        except Exception as e:
            council = f"[會議節點錯誤] {e}"

        return {
            "input": user_input,
            "user_refs": refs,
            "dispatch": dispatch,
            "all_data_refs": all_data_refs,
            "father": father,
            "son": son,
            "spirit": spirit,
            "council": council,
            "timestamp": datetime.now().isoformat(),
            "node_config": {r: f"{c.provider}/{c.model}" for r, c in self.nodes.items()},
        }

    # ═══════════════════════════════════════════════════════════════
    # v8.1+ 4-step Pipeline — Stage 1/2/3 LLM calls + helpers
    # ═══════════════════════════════════════════════════════════════

    # v8.14 P0-A — Per-stage baseline subset (token budget reduction).
    # Stage 4 Trinity voices keep the full 4-file load (spec strict).
    # Stage 1-3 transformation layers get only what they need:
    #   - Stage 1 (delabeling): KAIROS_CORE + PHYSICS_CONSTANTS
    #                            (label stripping doesn't need carrier_epistemics or trinity)
    #   - Stage 2 (explanation): + trinity (四律 depends on trinity baseline)
    #   - Stage 3 (filter):      + trinity (八律 uses LIE_COST + trinity weights)
    # Estimated savings: ~36 KB / query across Stage 1-3 input.
    _BASELINE_BY_STAGE = {
        "delabeling":  ["KAIROS_CORE.md", "PHYSICS_CONSTANTS_LITE.md"],
        # v8.30 p9: Stage 2 explanation now uses LITE PHYSICS_CONSTANTS to keep
        # system_content under Cerebras 8K-token limit (was 15K+ tokens →
        # 400 context_length_exceeded → chain stop → all-empty 4-law output).
        "explanation": ["KAIROS_CORE.md", "PHYSICS_CONSTANTS_LITE.md", "trinity.md"],
        # v8.14 A — Stage 3 八律 過濾層 uses PHYSICS_CONSTANTS_LITE (~3KB vs 25KB full)
        #            Stage 4 Trinity voices still get full constants.
        "filter":      ["KAIROS_CORE.md", "PHYSICS_CONSTANTS_LITE.md", "trinity.md"],
        # Trinity voices + dispatcher keep the full set (spec strict)
        "_full":       ["KAIROS_CORE.md", "PHYSICS_CONSTANTS.md",
                        "carrier_epistemics.md", "trinity.md"],
    }

    def _load_baseline_refs(self, stage_role: Optional[str] = None) -> str:
        """Load baseline references for an LLM call.

        v8.14 P0-A: stage_role selects subset to reduce Stage 1-3 token cost.
        - "delabeling" / "explanation" / "filter" → per-stage subset
        - None / unknown role → full set (backward compat for Trinity voices)
        """
        baseline_files = TrinityConsole._BASELINE_BY_STAGE.get(
            stage_role, TrinityConsole._BASELINE_BY_STAGE["_full"]
        )
        parts = []
        for filename in baseline_files:
            content = self.protocol.get(filename)
            if content:
                parts.append(f"━━━━━━ {filename} ━━━━━━\n{content}")
        return "\n\n".join(parts)

    def _load_stage_ref(self, ref_name: str) -> str:
        """Load a single stage-specific reference file from references/."""
        return self.protocol.get(ref_name, "")

    def get_knowledge_trace(self) -> List[Dict]:
        """Return the current query's bounded knowledge trace."""
        trace = _KNOWLEDGE_TRACE_CTX.get()
        return list(trace or [])

    def knowledge_health_summary(self) -> Dict:
        """Return a compact per-query knowledge health snapshot."""
        try:
            report = _knowledge_audit(root=self.data_dir.parent)
        except Exception as e:
            return {
                "clean": False,
                "error": f"{type(e).__name__}: {e}",
                "summary": {"issues": {"P0": 1, "P1": 0, "P2": 0, "P3": 0}},
            }
        counts = report.get("summary", {}).get("issues", {})
        coordinate_cards = _coordinate_cards_health(root=self.data_dir.parent)
        return {
            "clean": (
                not any(counts.get(level, 0) for level in ("P0", "P1", "P2"))
                and bool(coordinate_cards.get("ok", False))
            ),
            "manifest_sha256": report.get("manifest", {}).get("sha256"),
            "rag": report.get("rag", {}),
            "coordinate_cards": coordinate_cards,
            "summary": report.get("summary", {}),
            "issues": report.get("issues", [])[:10],
            "cau_structure": report.get("cau_structure", {}),
        }

    def _record_knowledge_trace(self, source: str, query: str, hits: List[Dict]) -> None:
        """Record concrete knowledge chunks used by the current query."""
        trace = _KNOWLEDGE_TRACE_CTX.get()
        if trace is None or not hits:
            return
        compact_hits = []
        for hit in hits[:12]:
            text = hit.get("text") or ""
            compact_hits.append({
                "id": hit.get("id", ""),
                "card_id": hit.get("card_id") or hit.get("id", ""),
                "source_file": hit.get("source_file", ""),
                "section": hit.get("section", ""),
                "score": hit.get("score", hit.get("retrieval_score")),
                "doc_id": hit.get("doc_id"),
                "doc_layer": hit.get("doc_layer"),
                "doc_canonical": hit.get("doc_canonical"),
                "doc_sha256": hit.get("doc_sha256"),
                "matched_terms": hit.get("matched_terms", []),
                "test": hit.get("test", ""),
                "text_preview": text[:500],
                "text_chars": len(text),
            })
        trace.append({
            "source": source,
            "query_preview": (query or "")[:500],
            "query_sha256": hashlib.sha256((query or "").encode("utf-8", errors="replace")).hexdigest(),
            "hit_count": len(hits),
            "hits": compact_hits,
        })

    def _record_ref_trace(self, ref: str, hits: List[Dict]) -> None:
        """Record files loaded by explicit --ref/context injection."""
        trace = _KNOWLEDGE_TRACE_CTX.get()
        if trace is None or not hits:
            return
        compact_hits = []
        for hit in hits[:20]:
            path = hit.get("path") or hit.get("source_file") or ""
            compact_hits.append({
                "ref": ref,
                "source_file": path,
                "doc_id": hit.get("doc_id"),
                "doc_layer": hit.get("doc_layer"),
                "doc_canonical": hit.get("doc_canonical"),
                "doc_sha256": hit.get("doc_sha256"),
                "bytes": hit.get("bytes"),
            })
        trace.append({
            "source": "manual_ref",
            "ref": ref,
            "hit_count": len(hits),
            "hits": compact_hits,
        })

    def _doc_trace_for_path(self, path: Path) -> Dict:
        """Build manifest metadata for a loaded local knowledge path."""
        root = self.data_dir.parent
        rel = ""
        try:
            rel = str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
        except Exception:
            rel = str(path)
        doc = None
        try:
            doc = _knowledge_documents_by_path(root=root).get(rel)
        except Exception:
            doc = None
        item = {
            "path": rel,
            "source_file": rel,
            "bytes": path.stat().st_size if path.exists() else None,
        }
        if doc is not None:
            item.update({
                "doc_id": doc.id,
                "doc_layer": doc.layer,
                "doc_canonical": doc.canonical,
                "doc_sha256": doc.current_sha256(root),
            })
        else:
            try:
                item["doc_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                pass
        return item

    def rag_block(self, query: str, k: int = 5, max_chars: int = 2500) -> str:
        """Query-time RAG retrieval (Phase 2). Returns prompt-ready block or "".

        Augments — does NOT replace — the static baseline preload. Silent
        fail-safe: if index missing / retrieval errors, returns "".
        """
        if not query:
            return ""
        try:
            card_context, card_hits = _coordinate_cards_block(
                query,
                root=self.data_dir.parent if hasattr(self, "data_dir") else Path(__file__).parent,
            )
            self._record_knowledge_trace("coordinate_cards", query, card_hits)
            r = _rag_get_retriever()
            if r is None:
                return card_context
            results = r.retrieve(query, k=k, max_total_chars=max_chars)
            self._record_knowledge_trace("rag_block", query, results)
            return card_context + r.format_results_for_prompt(results)
        except Exception:
            return ""

    # ═════════════════════════════════════════════════════════════════════
    # v8.30 p16 — CAU verbatim deep-content injection (Option A)
    # ═════════════════════════════════════════════════════════════════════
    # Background: even after v8.30 p15 retriever boost delivers CAU file's
    # deep sections into Stage 4 system_content, Father LLM still abstracts
    # away to protocol vocabulary (LIE_COST / FREEDOM_LOSS_ENTROPY / 律一-律四)
    # and ignores distinctive evidence (e.g. "1860年代工人退出工業革命",
    # "兩個月達一億用戶", "對齊到某些人的(0,0,0)而格式化其他人的(0,0,0)").
    # Live verify: surfacing rate 2/26 (8%) distinctive phrases.
    #
    # Fix: when user query mentions a CAU id, prepend the top 2 deep chunks
    # from that specific CAU file directly into user_content (not
    # system_content) with explicit MUST-QUOTE framing. User_content carries
    # much higher attention weight than system_content for LLMs, so this
    # forces the model to address the specific evidence.

    def cau_verbatim_prepend(self, query: str, max_chunks: int = 3,
                             max_chars: int = 1800) -> str:
        """Return a user_content prefix containing verbatim CAU chunks when
        the query explicitly mentions one or more CAU ids. Empty string when
        no CAU id detected — only triggers for relevant queries (won't pollute
        general conversation).
        """
        if not query:
            return ""
        try:
            from services.rag_retriever import _all_cau_ids_for_query
        except Exception:
            return ""
        # v8.30 p17 — union explicit + topic-inferred ids so natural-language
        # queries (no "CAU-NNN" string) also trigger user_content prepend.
        ids = _all_cau_ids_for_query(query)
        if not ids:
            return ""
        r = _rag_get_retriever()
        if r is None:
            return ""
        # Retrieve aggressively then filter to chunks from the matched CAU
        # files only — keeps the prepend small and on-topic.
        all_chunks = r.retrieve(query, k=12, max_total_chars=6000)
        matched: List[Dict] = []
        for cid in sorted(ids):
            for c in all_chunks:
                src = c.get("source_file", "").replace("\\", "/")
                fname = src.rsplit("/", 1)[-1]
                if (fname.startswith(f"CAU-{cid}_")
                        or fname.startswith(f"CAU{cid}_")):
                    # Skip the basic-參數 table — it's just metadata, not
                    # the substantive content we want to force-surface
                    sect = c.get("section", "") or ""
                    if "基本參數" in sect:
                        continue
                    matched.append(c)
        if not matched:
            return ""
        # Dedupe by section and cap
        seen = set()
        out: List[Dict] = []
        total = 0
        for c in matched:
            key = (c.get("source_file", ""), c.get("section", ""))
            if key in seen:
                continue
            seen.add(key)
            txt = (c.get("text") or "").strip()
            if total + len(txt) > max_chars and out:
                break
            out.append(c)
            total += len(txt)
            if len(out) >= max_chunks:
                break
        if not out:
            return ""
        self._record_knowledge_trace("cau_verbatim_prepend", query, out)
        # v8.30 p17 – distinguish explicit-id from topic-inferred so the
        # framing line is honest (query may not literally contain "CAU-NNN")
        try:
            from services.rag_retriever import _cau_ids_in_query
            explicit_ids = _cau_ids_in_query(query)
        except Exception:
            explicit_ids = set()
        if explicit_ids:
            framing = ("用戶 query 提到 "
                       + ", ".join(f"CAU-{i}" for i in sorted(ids))
                       + "。以下係 RAG 從 canonical CAU 檔案 retrieve 出嚟嘅實質段落。")
        else:
            framing = ("用戶 query 嘅 topic 對應到 canonical CAU 檔案 "
                       + ", ".join(f"CAU-{i}" for i in sorted(ids))
                       + "（系統自動從話題推斷，唔需要用戶記得編號）。"
                       "以下係 RAG retrieve 出嚟嘅實質段落。")
        lines = [
            "━━━ MUST_QUOTE_VERBATIM — RETRIEVED CAU 原文段落 ━━━",
            "",
            framing,
            "",
            "**絕對要求**：你嘅 response **必須**直接 quote 以下段落入面至少 2 句"
            " distinctive 內容（包含具體數字 / 日期 / 命名機制 / verbatim phrase），"
            "而**唔可以**淨係 paraphrase 成 protocol vocabulary"
            "（LIE_COST / FREEDOM_LOSS_ENTROPY / (0,0,0)）就算完成引用。"
            "若 quote 唔到 distinctive 內容，明文寫「呢個 CAU 嘅 retrieved chunk"
            "冇 specific evidence 答呢個 query」—— 唔好假裝有引。",
            "",
        ]
        for i, c in enumerate(out, 1):
            sect = c.get("section", "") or "(no section)"
            src = c.get("source_file", "").replace("\\", "/").rsplit("/", 1)[-1]
            lines.append(f"--- [{i}] {src} :: {sect} ---")
            lines.append(c.get("text", "").strip())
            lines.append("")
        lines.append("━━━ END_MUST_QUOTE_VERBATIM ━━━")
        return "\n".join(lines) + "\n\n"

    def _clean_json_output(self, s: str) -> str:
        """Strip potential markdown fences from LLM JSON output.
        (Kept for log clarity / backward compat. Real parsing path is
        `_extract_json_lenient` — see v8.14 P5.)"""
        cleaned = s.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```", 2)
            if len(parts) >= 2:
                inner = parts[1]
                if inner.startswith("json"):
                    inner = inner[4:]
                cleaned = inner.strip()
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3].strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]
        return cleaned

    # v8.14 P5 — Lenient JSON extraction from LLM responses.
    # Strategies (in order): strict parse → markdown fence strip → greedy {…} match.
    # Raises ValueError if all fail. Use at every LLM-output JSON parse site.
    _LENIENT_CODE_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(\{[\s\S]*?\})\s*```")
    # Greedy: largest { … } block in the text. Used as last resort when prose
    # surrounds the JSON without code fences.
    _LENIENT_ANY_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

    @staticmethod
    def _extract_json_lenient(text: str) -> Dict:
        """Robust JSON extraction from LLM response.

        Tries in order:
          1) strict json.loads on stripped text
          2) markdown ```json fence content
          3) greedy { … } regex (largest top-level object in text)

        Raises ValueError if no parseable JSON found.
        """
        if not isinstance(text, str):
            raise ValueError(f"Non-string input (type={type(text).__name__})")
        text = text.strip()
        if not text:
            raise ValueError("empty_response")

        # Try 1: strict parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try 2: markdown code fence (```json {...} ```)
        fence_match = TrinityConsole._LENIENT_CODE_FENCE_RE.search(text)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try 3: greedy match — first { to last } in text
        obj_match = TrinityConsole._LENIENT_ANY_OBJECT_RE.search(text)
        if obj_match:
            try:
                return json.loads(obj_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"no_parseable_json (length={len(text)})")

    @staticmethod
    def _is_semantic_empty(raw: str, *, min_chars: int = 40) -> Optional[str]:
        """v8.30 p12 — return a short reason string if raw content looks like
        prompt-echo / no-JSON / under threshold, else None.

        Triggers (any one fires):
          - raw has no `{` at all (model never emitted a JSON object)
          - raw shorter than min_chars after strip
          - raw clearly echoes the Stage-1 system-prompt scaffold
            (markdown section headers like `**階段 1` or `輸出 schema` AND
             still no `{` in the first half — i.e. didn't even start JSON
             before reciting the prompt).

        Caller uses this to raise EmptyContentError so call_with_failover
        walks to the next provider instead of silently parsing into empty
        fallback.
        """
        if not raw:
            return "empty_response"
        s = raw.strip()
        if len(s) < min_chars:
            return f"too_short ({len(s)} chars < {min_chars})"
        if "{" not in s:
            return "no_json_brace"
        # Prompt-echo signature: model recited the markdown scaffold before
        # (or instead of) emitting JSON. Two ways this fires:
        #   (a) brace appears > 150 chars after a head with ≥1 echo marker
        #       → model spent meaningful prose before getting to JSON
        #   (b) ≥2 echo markers anywhere in raw → model demonstrably echoed
        #       multiple prompt section headers
        # Either pattern means the LLM didn't follow OUTPUT_CONTRACT cleanly.
        echo_markers = ("**階段 1", "**STAGE 1", "輸出 schema", "Trinity baseline",
                        "去標籤化操作步驟", "OUTPUT_CONTRACT", "輸出 schema",
                        "操作步驟", "**STAGE", "**階段")
        first_brace = s.find("{")
        head = s[:first_brace] if first_brace > 0 else ""
        head_hits = sum(1 for m in echo_markers if m in head)
        whole_hits = sum(1 for m in echo_markers if m in s)
        if head_hits >= 1 and first_brace > 150:
            return f"prompt_echo_head (first_brace={first_brace}, head_hits={head_hits})"
        if whole_hits >= 2:
            return f"prompt_echo_whole (hits={whole_hits})"
        return None

    async def _parse_json_with_retry(
        self,
        raw_output: str,
        original_messages: List[Dict],
        node_cfg: NodeConfig,
        adapter,
        fallback: Dict,
        max_retries: int = 3,
    ) -> Dict:
        """Common JSON parsing with retry pattern for Stage 1-3 LLMs.
        v8.14 P5 — uses `_extract_json_lenient` instead of strict json.loads,
        so prose-wrapped or multiline pretty-printed responses parse on first try
        without burning retry budget."""
        try:
            return self._extract_json_lenient(raw_output)
        except (ValueError, json.JSONDecodeError):
            pass

        current_output = raw_output
        for _ in range(max_retries):
            retry_messages = original_messages + [
                {"role": "assistant", "content": current_output},
                {"role": "user", "content": "Output 必須係嚴格 JSON 格式，依照 schema。請重新輸出 JSON only，唔好加任何其他文字。"},
            ]
            try:
                current_output = await adapter.call(
                    messages=retry_messages,
                    model=node_cfg.model,
                    temperature=node_cfg.temperature,
                    max_tokens=node_cfg.max_tokens,
                )
                return self._extract_json_lenient(current_output)
            except (ValueError, json.JSONDecodeError, Exception):
                continue

        fallback = dict(fallback)
        fallback["_parse_error"] = "JSON parse failed after retries"
        fallback["_last_raw_output"] = (current_output or "")[:500]
        return fallback

    def _get_stage_adapter(self, role: str):
        """Resolve adapter + node_cfg for a stage role.
        v8.8 R7 — checks _LLM_OVERRIDE_CTX for per-mode override; if set,
        builds a synthetic NodeConfig combining override provider/model with
        the named profile's api_base + api_key_env.
        v8.14 B — also checks self.stage_overrides[role] for per-stage primary
        provider (lets a heavy stage e.g. filter route to a higher-context
        provider without affecting Trinity voices). Per-mode LLM_OVERRIDE_CTX
        takes precedence over per-stage override (Trinity voice's choice wins)."""
        base_cfg = self.nodes.get(role)
        if not base_cfg:
            raise RuntimeError(f"{role} node not configured in nodes.yaml")
        # v8.14 B — apply per-stage override first (low priority)
        # so per-mode _LLM_OVERRIDE_CTX (high priority) can still override on top.
        stage_ovr = self.stage_overrides.get(role) if hasattr(self, 'stage_overrides') else None
        if stage_ovr and stage_ovr.get("provider") and not _LLM_OVERRIDE_CTX.get():
            base_cfg = self._apply_stage_override(base_cfg, stage_ovr)
        node_cfg = self._apply_llm_override(base_cfg)
        adapter_cls = ADAPTERS.get(node_cfg.provider)
        if adapter_cls is None:
            raise ValueError(f"未知 provider：{node_cfg.provider}")
        api_key = os.environ.get(node_cfg.api_key_env) if node_cfg.api_key_env else None
        if node_cfg.provider != "ollama" and node_cfg.api_key_env and not api_key:
            raise EnvironmentError(
                f"{role} 節點：環境變數 {node_cfg.api_key_env} 未設定。"
            )
        adapter = adapter_cls(api_key=api_key, api_base=node_cfg.api_base)
        return adapter, node_cfg

    def _apply_stage_override(self, base_cfg: "NodeConfig", stage_ovr: Dict) -> "NodeConfig":
        """v8.14 B — substitute provider/model/api_base/api_key_env from a named
        profile (stage_overrides.<role>.provider). Falls through to base_cfg if
        profile not found.
        v8.14 P6 — also honors optional max_tokens + temperature overrides at
        stage_overrides.<role>.max_tokens / temperature; falls back to base_cfg
        when not set."""
        profile_name = stage_ovr.get("provider")
        if not profile_name or not self.failover_cfg or not self.failover_cfg.profiles:
            return base_cfg
        profile = self.failover_cfg.profiles.get(profile_name)
        if not profile or not profile.enabled:
            return base_cfg
        # v8.14 P6 — pick override temp/max_tokens if explicitly set
        ovr_temp = stage_ovr.get("temperature", base_cfg.temperature)
        ovr_max_tokens = stage_ovr.get("max_tokens", base_cfg.max_tokens)
        return NodeConfig(
            role=base_cfg.role,
            provider=profile.provider,
            model=profile.default_model or base_cfg.model,
            api_key_env=profile.api_key_env or base_cfg.api_key_env,
            api_base=profile.api_base or base_cfg.api_base,
            temperature=ovr_temp,
            max_tokens=ovr_max_tokens,
        )

    def _apply_llm_override(self, base_cfg: "NodeConfig") -> "NodeConfig":
        """v8.8 R7 — if _LLM_OVERRIDE_CTX has a per-mode override, return a
        synthetic NodeConfig merging override's provider/model with the named
        profile's api_base + api_key_env. Falls through to base_cfg if no override."""
        override = _LLM_OVERRIDE_CTX.get()
        if not override:
            return base_cfg
        # Resolve api_base + api_key_env from named profile (if given)
        api_base = base_cfg.api_base
        api_key_env = base_cfg.api_key_env
        profile_name = override.get("api_profile")
        if profile_name:
            profile = self.failover_cfg.profiles.get(profile_name) if hasattr(self, 'failover_cfg') else None
            if profile is None:
                profile = (self.failover_cfg.profiles.get(profile_name)
                           if self.failover_cfg and self.failover_cfg.profiles else None)
            if profile:
                api_base = profile.api_base or api_base
                api_key_env = profile.api_key_env or api_key_env
        return NodeConfig(
            role=base_cfg.role,
            provider=override.get("provider", base_cfg.provider),
            model=override.get("model", base_cfg.model),
            api_key_env=api_key_env,
            api_base=api_base,
            temperature=base_cfg.temperature,
            max_tokens=base_cfg.max_tokens,
        )

    async def call_delabeling(self, user_input: str) -> Dict:
        """Stage 1: 去標籤化 LLM call."""
        with tracer.start_as_current_span("trinity.stage1.delabeling") as _span:
            _span.set_attribute("uruk.stage", 1)
            _span.set_attribute("uruk.user_input_length", len(user_input or ""))
            _result = await self._call_delabeling_inner(user_input)
            set_trinity_attrs(
                _span,
                verdict=_result.get("abort_signal"),
                veto_type=_result.get("veto_type"),
            )
            if _result.get("abort_signal") == "yes":
                emit_event(_span, "stage1.abort_signal",
                           veto=str(_result.get("veto_type", "")),
                           interrupt=str(_result.get("interrupt_type", "")))
            return _result

    async def _call_delabeling_inner(self, user_input: str) -> Dict:
        refs_content = self._load_baseline_refs(stage_role="delabeling")
        delabeling_ref = self._load_stage_ref("delabeling.md")
        prompt = self.prompts.get("delabeling", "")
        if not prompt:
            raise RuntimeError("delabeling prompt 唔存在 (config/prompts/delabeling.txt)")

        # v8.30 p7: prepend canonical anchor to lock 八律/四律/方程式 grounding.
        _anc = getattr(self, "canonical_anchor", "") or ""
        _anc_block = f"{_anc}\n\n" if _anc else ""
        system_content = with_runtime_identity(f"{_anc_block}{prompt}\n\n--------\n{refs_content}\n\n{delabeling_ref}")
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_input},
        ]

        # v8.30 p6: route through call_with_failover so stage_overrides.fallback
        # actually activates on Groq 429. Previously _call_delabeling_inner used
        # adapter.call(...) directly → no failover → empty schema on rate-limit.
        _, node_cfg = self._get_stage_adapter("delabeling")
        chain = self._resolve_chain("delabeling")
        primary_api_key = (os.environ.get(node_cfg.api_key_env)
                           if node_cfg.api_key_env else None)

        async def _delab_one_call(*, provider: str, model: str,
                                  api_base: Optional[str], api_key: Optional[str]) -> str:
            adapter_cls = ADAPTERS.get(provider)
            if adapter_cls is None:
                raise ValueError(f"未知 provider：{provider}")
            adapter = adapter_cls(api_key=api_key, api_base=api_base)
            raw = await adapter.call(
                messages=messages, model=model,
                temperature=node_cfg.temperature,
                max_tokens=node_cfg.max_tokens,
            )
            # v8.30 p12 — content validation gate. If the model returned 200 OK
            # but the body is semantically empty (prompt-echo / no JSON / too
            # short), raise EmptyContentError so call_with_failover treats it
            # as a failover trigger and walks to the next provider. Previously
            # such garbage was silently passed to the parser → empty schema →
            # detected_labels = [] → UI rendered "(none)".
            reason = TrinityConsole._is_semantic_empty(raw)
            if reason:
                raise EmptyContentError(
                    f"Stage 1 ({provider}/{model}) semantic-empty: {reason}"
                )
            return raw

        try:
            raw_output = await call_with_failover(
                primary_call=_delab_one_call,
                chain=chain,
                primary_profile_name=self._infer_primary_profile_name(node_cfg),
                primary_provider=node_cfg.provider,
                primary_model=node_cfg.model,
                primary_api_base=node_cfg.api_base,
                primary_api_key=primary_api_key,
                role="delabeling",
                tracker=self.health,
                cfg=self.failover_cfg,
            )
        except AllProfilesFailedError as e:
            # v8.30 p12 — every chain entry returned empty/garbage. Surface a
            # structural-failure marker so UI can render "⚠ Stage 1 結構性失敗"
            # instead of silently showing (none).
            return {
                "delabeled_input": user_input,
                "detected_labels": [],
                "veto_detected": "no",
                "veto_type": None,
                "interrupt_detected": "no",
                "interrupt_type": None,
                "abort_signal": "no",
                "abort_context": "Stage 1 all providers returned empty/garbage",
                "_call_error": str(e),
                "_structural_failure": "all_providers_empty_content",
            }
        except Exception as e:
            return {
                "delabeled_input": user_input,
                "detected_labels": [],
                "veto_detected": "no",
                "veto_type": None,
                "interrupt_detected": "no",
                "interrupt_type": None,
                "abort_signal": "no",
                "abort_context": f"Stage 1 LLM call fail ({e})",
                "_call_error": str(e),
                "_structural_failure": "call_exception",
            }

        # v8.30 p9 — adapter handle for _parse_json_with_retry (call_with_failover
        # consumed the inner adapter closure; rebuild for retry compatibility).
        _retry_cls = ADAPTERS.get(node_cfg.provider)
        adapter = _retry_cls(
            api_key=primary_api_key, api_base=node_cfg.api_base
        ) if _retry_cls else None
        parsed = await self._parse_json_with_retry(
            raw_output, messages, node_cfg, adapter,
            fallback={
                "delabeled_input": user_input,
                "detected_labels": [],
                "veto_detected": "no",
                "veto_type": None,
                "interrupt_detected": "no",
                "interrupt_type": None,
                "abort_signal": "no",
                "abort_context": "Stage 1 schema parse fail",
            },
        )
        # v8.30 p12 — tag structural parse-retry exhaustion so UI can surface
        # "⚠ Stage 1 parser exhausted" instead of silently showing (none).
        if parsed.get("_parse_error"):
            parsed.setdefault("_structural_failure", "parse_retry_exhausted")
        return parsed

    async def call_explanation(self, stage1_output: Dict) -> Dict:
        """Stage 2: 解釋層 LLM call (四律 + 哲學貫穿律)."""
        with tracer.start_as_current_span("trinity.stage2.explanation") as _span:
            _span.set_attribute("uruk.stage", 2)
            _result = await self._call_explanation_inner(stage1_output)
            set_trinity_attrs(_span,
                              verdict=_result.get("abort_signal"),
                              veto_type=_result.get("veto_type"))
            return _result

    async def _call_explanation_inner(self, stage1_output: Dict) -> Dict:
        refs_content = self._load_baseline_refs(stage_role="explanation")
        explanation_ref = self._load_stage_ref("explanation_layer.md")
        prompt = self.prompts.get("explanation", "")
        if not prompt:
            raise RuntimeError("explanation prompt 唔存在 (config/prompts/explanation.txt)")

        s1_json = json.dumps(stage1_output, ensure_ascii=False, indent=2)
        user_content = (
            f"━━━ Stage 1 (去標籤化) 輸出 ━━━\n{s1_json}\n\n"
            f"━━━ 你嘅任務 ━━━\n"
            f"基於以上 cleansed input 做四律 + 哲學貫穿律分析。\n"
            f"請輸出 JSON only，依照 schema。"
        )

        # v8.30 p7: prepend canonical anchor to lock 八律/四律/方程式 grounding.
        _anc = getattr(self, "canonical_anchor", "") or ""
        _anc_block = f"{_anc}\n\n" if _anc else ""
        system_content = with_runtime_identity(f"{_anc_block}{prompt}\n\n--------\n{refs_content}\n\n{explanation_ref}")
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # v8.30 p6: route through call_with_failover (same fix as delabeling).
        _, node_cfg = self._get_stage_adapter("explanation")
        chain = self._resolve_chain("explanation")
        primary_api_key = (os.environ.get(node_cfg.api_key_env)
                           if node_cfg.api_key_env else None)

        async def _expl_one_call(*, provider: str, model: str,
                                 api_base: Optional[str], api_key: Optional[str]) -> str:
            adapter_cls = ADAPTERS.get(provider)
            if adapter_cls is None:
                raise ValueError(f"未知 provider：{provider}")
            adapter = adapter_cls(api_key=api_key, api_base=api_base)
            return await adapter.call(
                messages=messages, model=model,
                temperature=node_cfg.temperature,
                max_tokens=node_cfg.max_tokens,
            )

        try:
            raw_output = await call_with_failover(
                primary_call=_expl_one_call,
                chain=chain,
                primary_profile_name=self._infer_primary_profile_name(node_cfg),
                primary_provider=node_cfg.provider,
                primary_model=node_cfg.model,
                primary_api_base=node_cfg.api_base,
                primary_api_key=primary_api_key,
                role="explanation",
                tracker=self.health,
                cfg=self.failover_cfg,
            )
        except Exception as e:
            return {
                "geography_analysis": "",
                "religion_analysis": "",
                "psychology_analysis": "",
                "history_analysis": "",
                "philosophy_dispatch": "",
                "causal_summary": "",
                "veto_detected": "no",
                "veto_type": None,
                "interrupt_detected": "no",
                "interrupt_type": None,
                "abort_signal": "no",
                "abort_context": f"Stage 2 LLM call fail ({e})",
                "_call_error": str(e),
            }

        # v8.30 p9 — adapter handle for _parse_json_with_retry.
        _retry_cls = ADAPTERS.get(node_cfg.provider)
        adapter = _retry_cls(
            api_key=primary_api_key, api_base=node_cfg.api_base
        ) if _retry_cls else None
        return await self._parse_json_with_retry(
            raw_output, messages, node_cfg, adapter,
            fallback={
                "geography_analysis": "Stage 2 schema parse fail",
                "religion_analysis": "",
                "psychology_analysis": "",
                "history_analysis": "",
                "philosophy_dispatch": "",
                "causal_summary": "",
                "veto_detected": "no",
                "veto_type": None,
                "interrupt_detected": "no",
                "interrupt_type": None,
                "abort_signal": "no",
                "abort_context": "Stage 2 schema parse fail",
            },
        )

    async def call_filter(self, stage1_output: Dict, stage2_output: Dict) -> Dict:
        """Stage 3: 過濾層 LLM call (八律 + 動態權重 + 跨律湧現).

        v8.14 B-fix — uses `call_with_failover` so stage_overrides.filter.fallback
        chain is actually walked when primary 429s / quotas-out. Previously bare
        try/except → fail-safe dict, fallback chain dormant."""
        with tracer.start_as_current_span("trinity.stage3.filter") as _span:
            _span.set_attribute("uruk.stage", 3)
            _result = await self._call_filter_inner(stage1_output, stage2_output)
            # 8-law scores → numeric attributes for histogram dashboards
            try:
                scores = self._parse_eight_law_scores(_result) if hasattr(self, "_parse_eight_law_scores") else {}
                for _k, _v in scores.items():
                    if isinstance(_v, (int, float)) and not _k.startswith("_"):
                        _span.set_attribute(f"uruk.law.{_k}", float(_v))
            except Exception:
                pass
            return _result

    async def _call_filter_inner(self, stage1_output: Dict, stage2_output: Dict) -> Dict:
        refs_content = self._load_baseline_refs(stage_role="filter")
        eight_laws_ref = self._load_stage_ref("eight_laws.md")
        prompt = self.prompts.get("filter", "")
        if not prompt:
            raise RuntimeError("filter prompt 唔存在 (config/prompts/filter.txt)")

        s1_json = json.dumps(stage1_output, ensure_ascii=False, indent=2)
        s2_json = json.dumps(stage2_output, ensure_ascii=False, indent=2)
        user_content = (
            f"━━━ Stage 1 (去標籤化) 輸出 ━━━\n{s1_json}\n\n"
            f"━━━ Stage 2 (解釋層) 輸出 ━━━\n{s2_json}\n\n"
            f"━━━ 你嘅任務 ━━━\n"
            f"基於 cleansed input + causal analysis 做八律過濾。\n"
            f"識別 signal_profile + dominant_laws + emergent_nodes + filter_verdict。\n"
            f"請輸出 JSON only，依照 schema。"
        )

        # v8.30 p7: prepend canonical anchor to lock 八律/四律/方程式 grounding.
        _anc = getattr(self, "canonical_anchor", "") or ""
        _anc_block = f"{_anc}\n\n" if _anc else ""
        system_content = with_runtime_identity(f"{_anc_block}{prompt}\n\n--------\n{refs_content}\n\n{eight_laws_ref}")
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # v8.14 B-fix — resolve override-applied cfg + chain
        _adapter_unused, node_cfg = self._get_stage_adapter("filter")
        chain = self._resolve_chain("filter")
        primary_api_key = (os.environ.get(node_cfg.api_key_env)
                           if node_cfg.api_key_env else None)

        async def _filter_one_call(*, provider: str, model: str,
                                    api_base: Optional[str], api_key: Optional[str]) -> str:
            adapter_cls = ADAPTERS.get(provider)
            if adapter_cls is None:
                raise ValueError(f"未知 provider：{provider}")
            adapter = adapter_cls(api_key=api_key, api_base=api_base)
            return await adapter.call(
                messages=messages,
                model=model,
                temperature=node_cfg.temperature,
                max_tokens=node_cfg.max_tokens,
            )

        try:
            raw_output = await call_with_failover(
                primary_call=_filter_one_call,
                chain=chain,
                primary_profile_name=self._infer_primary_profile_name(node_cfg),
                primary_provider=node_cfg.provider,
                primary_model=node_cfg.model,
                primary_api_base=node_cfg.api_base,
                primary_api_key=primary_api_key,
                role="filter",
                tracker=self.health,
                cfg=self.failover_cfg,
            )
        except (AllProfilesFailedError, Exception) as e:
            return {
                "law0_love_check": "",
                "law1_art": {"score": 0.0, "analysis": ""},
                "law2_psychology": {"score": 0.0, "analysis": ""},
                "law3_physics": {"score": 0.0, "analysis": ""},
                "law4_chemistry": {"score": 0.0, "analysis": ""},
                "law5_science": {"score": 0.0, "analysis": ""},
                "law6_philosophy": {"score": 0.0, "analysis": ""},
                "law7_geography": {"score": 0.0, "analysis": ""},
                "law8_religion": {"score": 0.0, "analysis": ""},
                "signal_profile": "default",
                "dominant_laws": [3, 6, 5, 7],
                "emergent_nodes": [],
                "filter_verdict": "WEAK",
                "veto_detected": "no",
                "veto_type": None,
                "interrupt_detected": "no",
                "interrupt_type": None,
                "abort_signal": "no",
                "abort_context": f"Stage 3 chain exhausted ({type(e).__name__}: {e})",
                "_call_error": str(e),
            }

        # Build a no-op adapter handle for _parse_json_with_retry compatibility.
        # Retry uses the primary node_cfg by design (retries are about schema
        # compliance, not provider failover).
        adapter_for_retry = ADAPTERS.get(node_cfg.provider)
        adapter = adapter_for_retry(
            api_key=primary_api_key, api_base=node_cfg.api_base
        ) if adapter_for_retry else None

        parsed = await self._parse_json_with_retry(
            raw_output, messages, node_cfg, adapter,
            fallback={
                "law0_love_check": "Stage 3 schema parse fail",
                "law1_art": {"score": 0.0, "analysis": ""},
                "law2_psychology": {"score": 0.0, "analysis": ""},
                "law3_physics": {"score": 0.0, "analysis": ""},
                "law4_chemistry": {"score": 0.0, "analysis": ""},
                "law5_science": {"score": 0.0, "analysis": ""},
                "law6_philosophy": {"score": 0.0, "analysis": ""},
                "law7_geography": {"score": 0.0, "analysis": ""},
                "law8_religion": {"score": 0.0, "analysis": ""},
                "signal_profile": "default",
                "dominant_laws": [3, 6, 5, 7],
                "emergent_nodes": [],
                "filter_verdict": "WEAK",
                "veto_detected": "no",
                "veto_type": None,
                "interrupt_detected": "no",
                "interrupt_type": None,
                "abort_signal": "no",
                "abort_context": "Stage 3 schema parse fail",
            },
        )
        return parsed

    def _format_pipeline_context(self, **stages) -> str:
        """Format Stage 1-3 outputs as enriched context for Stage 4 nodes."""
        if not stages:
            return ""

        parts = ["\n━━━ PIPELINE CONTEXT (Stage 1-3 outputs) ━━━"]

        s1 = stages.get("stage1")
        if s1:
            parts.append("\n--- Stage 1 (去標籤化) ---")
            parts.append(f"Delabeled input: {s1.get('delabeled_input', '')}")
            detected = s1.get("detected_labels") or []
            if detected and isinstance(detected, list):
                parts.append(f"Detected labels: {len(detected)} 個")
                for lbl in detected[:5]:
                    if isinstance(lbl, dict):
                        parts.append(f"  - {lbl.get('label', '')} → {lbl.get('physical_param', '')}")

        s2 = stages.get("stage2")
        if s2:
            parts.append("\n--- Stage 2 (解釋層 · 四律 + 哲學貫穿律) ---")
            parts.append(f"Causal summary: {s2.get('causal_summary', '')}")
            # v8.30 fix: render ALL four laws (canonical: 地理/宗教/心理/歷史)
            # plus the philosophical 貫穿律. Pre-fix bug only surfaced 律一+律三,
            # leaving 律二 (宗教) and 律四 (歷史) blank in council context.
            parts.append(f"律一·地理 (Geography): {str(s2.get('geography_analysis', '')).strip()[:300] or '(empty)'}")
            parts.append(f"律二·宗教 (Religion): {str(s2.get('religion_analysis', '')).strip()[:300] or '(empty)'}")
            parts.append(f"律三·心理 (Psychology): {str(s2.get('psychology_analysis', '')).strip()[:300] or '(empty)'}")
            parts.append(f"律四·歷史 (History): {str(s2.get('history_analysis', '')).strip()[:300] or '(empty)'}")
            parts.append(f"貫穿律·哲學 (Philosophy dispatch): {str(s2.get('philosophy_dispatch', '')).strip()[:300] or '(empty)'}")

        s3 = stages.get("stage3")
        if s3:
            parts.append("\n--- Stage 3 (過濾層) ---")
            parts.append(f"Filter verdict: {s3.get('filter_verdict', '')}")
            parts.append(f"Signal profile: {s3.get('signal_profile', '')}")
            parts.append(f"Dominant laws: {s3.get('dominant_laws', [])}")
            emergent = s3.get("emergent_nodes", [])
            if emergent and isinstance(emergent, list):
                parts.append(f"Emergent nodes ({len(emergent)} 個):")
                for node in emergent:
                    if isinstance(node, dict):
                        layer = node.get("layer", "")
                        insight = node.get("insight", "")
                        parts.append(f"  - [{layer}] {insight}")

        parts.append("")
        return "\n".join(parts)

    def _format_dispatcher_input(self, user_input: str, stage1: Dict, stage2: Dict, stage3: Dict,
                                  historical_context: str = "",
                                  in_session_context: str = "") -> str:
        """Format pipeline-aware input for dispatcher (Stage 4 routing).

        v8.4: `historical_context` (optional) is the rendered "歷史脈絡" block
        from `_format_history_block`. When non-empty, it's prepended so the
        dispatcher LLM can factor recent sessions into mode + reference choice.

        v8.11: `in_session_context` (optional) is the rendered in-session
        conversation thread (turns 1..N within current browser session). Order
        per Q7: cross-session first (older), in-session second (more recent,
        nearer to current input for recency bias).
        """
        history_prefix = f"{historical_context}\n\n" if historical_context else ""
        in_session_prefix = f"{in_session_context}\n\n" if in_session_context else ""

        # v8.14 Phase C: Module T (CivilizationalClock) snapshot. Only injected
        # when the user query references Module T concepts (see should_surface).
        clock_snap = civilizational_clock.snapshot(user_input)
        clock_block = ""
        if clock_snap.get("active"):
            const = clock_snap.get("constants", {})
            cost_match = clock_snap.get("cost_transfer_match")
            predictions = clock_snap.get("predictions") or {}
            next_leap = predictions.get("next_tech_leap_year") or {}
            window_close = predictions.get("anti_format_window_close") or {}
            lines = ["━━━ Module T — Civilizational Clock snapshot (v8.30) ━━━",
                     f"today: {clock_snap.get('today', '')}",
                     "constants (Layer-3 calibrated):",
                     f"  Eq1 canonical: gap(n) = {const.get('eq1_base_gap')} × {const.get('eq1_decay_ratio')}^n  (fallback ratio={const.get('tech_ratio')})",
                     f"  Eq2 canonical: delay = {const.get('eq2_delay_coeff')} / ln(velocity)  (fallback band={const.get('anti_format_delay_band')}yr)",
                     f"  Eq3 scale_ratio={const.get('scale_ratio')}, generation_yr={const.get('generation_years')}",
                     f"  Eq4 cost: W = {const.get('cost_coeff')} × P^({const.get('cost_exponent')}), waves={const.get('cost_manifest_waves')}yr",
                     f"  Eq5 collapse: external_div={const.get('collapse_external_divisor')}, internal_div={const.get('collapse_internal_divisor')}",
                     "canonical predictions (deterministic, not LLM-derived):"]
            if next_leap.get("predicted_year"):
                lines.append(f"  → next tech leap year: {next_leap['predicted_year']} "
                             f"({next_leap.get('derivation', '')})")
            if window_close.get("close_year"):
                lines.append(f"  → anti-formatting window close: {window_close['close_year']} "
                             f"({window_close.get('derivation', '')})")
            lines.append("calibration references:")
            for ref in clock_snap.get("calibration_references", []):
                lines.append(f"  - {ref.get('period')}: anti-format-delay={ref.get('anti_format_delay_yr')}yr; "
                             f"cost-transfer hit: {ref.get('cost_transfer_75yr_hit', '')}")
            if cost_match:
                lines.append(f"COST_TRANSFER_MATCH: anchor={cost_match['year_anchor']} → "
                             f"manifest={cost_match['year_manifest']} (gap={cost_match['gap_years']}yr)")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            clock_block = "\n".join(lines) + "\n\n"

        return (
            f"{history_prefix}"
            f"{in_session_prefix}"
            f"{clock_block}"
            f"用戶輸入：\n{user_input}\n\n"
            f"━━━ Stage 1-3 Pipeline Outputs ━━━\n\n"
            f"--- Stage 1 (delabeled) ---\n"
            f"delabeled_input: {stage1.get('delabeled_input', '')}\n\n"
            f"--- Stage 2 (causal) ---\n"
            f"causal_summary: {stage2.get('causal_summary', '')}\n"
            f"philosophy_dispatch: {stage2.get('philosophy_dispatch', '')}\n\n"
            f"--- Stage 3 (filter) ---\n"
            f"filter_verdict: {stage3.get('filter_verdict', '')}\n"
            f"signal_profile: {stage3.get('signal_profile', '')}\n"
            f"dominant_laws: {stage3.get('dominant_laws', [])}\n"
            f"emergent_nodes count: {len(stage3.get('emergent_nodes', []) or [])}\n"
        )

    @staticmethod
    def _format_in_session_history(turns: List[Dict], mode_filter: Optional[str] = None) -> str:
        """v8.11 — Format in-session conversation thread for dispatcher prompt.

        v8.30 p13 (latency cap) — sliding window + per-turn truncation:
          - Always include the 3 most recent turns in full (1500-char council).
          - Older turns (4th-newest onwards) → truncate council to 400 chars
            and prefix `[older, abridged]`.
          - At 8+ prior turns, drop turns older than #(N-6) entirely;
            insert a `[... N turns omitted ...]` marker.
        Goal: keep Stage 4 prompt under ~12KB even at turn 10+, restoring
        sub-300s per-turn latency.

        Args:
            turns: list of ConvTurn dicts (or pydantic models cast to dict). Each
                turn has {turn_id, timestamp, input, modes: {mode_id: {council, verdict, veto_type}}}.
            mode_filter: when set (Option A per Q4), only include turns where this
                mode participated. Each turn's section uses ONLY that mode's
                council text.

        Returns the formatted block, or empty string if no relevant turns.
        """
        if not turns:
            return ""
        # v8.30 p13 — sliding window: keep at most 6 turns (3 recent full + 3 older abridged)
        _total = len(turns)
        if _total > 6:
            _kept = turns[-6:]
            _omitted_count = _total - 6
            _omit_marker = (
                f"[... 已省略 {_omitted_count} 個更早回合 "
                f"(老 turn 全文喺 dispatcher RAG block 仲可以查到) ...]"
            )
        else:
            _kept = list(turns)
            _omit_marker = None
        # Identify which kept turns get truncation (older = first half)
        _full_threshold = max(0, len(_kept) - 3)  # last 3 get full quote
        lines = ["━━━ 對話歷史（in-session）━━━"]
        if _omit_marker:
            lines.append(_omit_marker)
        included = 0
        for _i, t in enumerate(_kept):
            # Pydantic model may have .model_dump(); accept dict too
            if hasattr(t, "model_dump"):
                t_dict = t.model_dump()
            else:
                t_dict = t
            modes = t_dict.get("modes") or {}
            # v8.30 p13 — older turns get 400-char abridgement, recent get 1500
            _is_old = _i < _full_threshold
            _quota = 400 if _is_old else 1500
            _old_tag = " [older, abridged]" if _is_old else ""
            if mode_filter:
                # Skip turns that didn't use this mode
                if mode_filter not in modes:
                    continue
                # Use only this mode's council
                mode_data = modes[mode_filter]
                council_text = (mode_data.get("council") or "")[:_quota]
                verdict_tag = mode_data.get("verdict") or ""
                veto_tag = mode_data.get("veto_type") or ""
                extra = []
                if verdict_tag and verdict_tag != "consensus":
                    extra.append(verdict_tag)
                if veto_tag and veto_tag != "none":
                    extra.append(f"veto={veto_tag}")
                extra_str = f" [{' / '.join(extra)}]" if extra else ""
                lines.append(f"[Turn {t_dict.get('turn_id', '?')}, {t_dict.get('timestamp', '')[:16]}]{extra_str}{_old_tag}")
                lines.append(f"用戶: {t_dict.get('input', '').strip()[:500]}")
                lines.append(f"會議: {council_text.strip()}")
                lines.append("")
                included += 1
            else:
                # No filter: concat all modes' council texts
                lines.append(f"[Turn {t_dict.get('turn_id', '?')}, {t_dict.get('timestamp', '')[:16]}]{_old_tag}")
                lines.append(f"用戶: {t_dict.get('input', '').strip()[:500]}")
                for mid, mdata in modes.items():
                    if hasattr(mdata, "model_dump"):
                        mdata = mdata.model_dump()
                    council_text = (mdata.get("council") or "")[:_quota]
                    if not council_text:
                        continue
                    label = mid if mid != "_default" else "會議"
                    lines.append(f"{label}: {council_text.strip()}")
                lines.append("")
                included += 1
        if included == 0:
            return ""
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def _format_council_input(
        self,
        original_input: str,
        dispatch: Dict,
        results: Dict,
        pipeline_stages: Optional[Dict] = None,
    ) -> str:
        """Format input for council node, including pipeline stages + 父子靈 outputs."""
        parts = [
            "━━━ DISPATCHER 決定 ━━━",
            f"Mode: {dispatch.get('mode', '')} ({dispatch.get('mode_rationale', '')})",
            f"References loaded: {', '.join(dispatch.get('references', []))}",
            "",
        ]

        if pipeline_stages:
            parts.append(self._format_pipeline_context(**pipeline_stages))

        # Fix F: defensive voice-block extraction (handles legacy 4-block voices)
        father_out = self._extract_voice_block(str(results.get("father", "")), "father")
        son_out    = self._extract_voice_block(str(results.get("son", "")),    "son")
        spirit_out = self._extract_voice_block(str(results.get("spirit", "")), "spirit")

        parts.extend([
            "━━━ 原始問題 ━━━",
            original_input,
            "",
            "━━━ 聖父輸出（邏輯主導，已 parse 為 single voice block）━━━",
            father_out,
            "",
            "━━━ 聖子輸出（共鳴主導，已 parse 為 single voice block）━━━",
            son_out,
            "",
            "━━━ 聖靈輸出（反叛主導，已 parse 為 single voice block）━━━",
            spirit_out,
            "",
        ])

        return "\n".join(parts)

    # ═══════════════════════════════════════════════════════════════
    # Fix F + γ: Voice block parser + pipeline execution detection
    # ═══════════════════════════════════════════════════════════════

    def _detect_pipeline_execution_mode(self) -> str:
        """Detect whether Stage 4 Trinity runs as single_llm or multi_llm.

        single_llm: father/son/spirit all use the same provider + model.
        multi_llm: at least 2 of father/son/spirit use a different provider or model.

        This is an execution topology label only; it is not Spirit Mode A/B.
        """
        voices = ["father", "son", "spirit"]
        configs = []
        for v in voices:
            cfg = self.nodes.get(v)
            if cfg:
                configs.append((cfg.provider, cfg.model))
        if len(set(configs)) <= 1:
            return "single_llm"
        return "multi_llm"

    def _detect_pipeline_mode(self) -> str:
        """Backward-compatible alias for pipeline execution topology."""
        return self._detect_pipeline_execution_mode()

    def _voice_mode_hint(self, role: str) -> str:
        """Return system-message hint about pipeline execution for voice nodes.

        multi_llm: explicit reminder that this is one voice of three.
        single_llm: legacy 4-block emission acceptable.
        """
        if role not in ("father", "son", "spirit"):
            return ""
        mode = self._detect_pipeline_execution_mode()
        if mode == "multi_llm":
            voice_map = {"father": "聖父 FATHER", "son": "聖子 SON", "spirit": "聖靈 SPIRIT"}
            return (
                f"\n\n════════ [PIPELINE EXECUTION: multi_llm] ════════\n"
                f"你係 3 個獨立 voice nodes 嘅其中一個（{voice_map[role]}）。\n"
                f"只貢獻你嘅 SINGLE voice block。Council 由獨立 LLM 整合 3 個 voice。\n"
                f"絕對唔輸出其他 voice 嘅 block 或 [回應 RESPONSE] / [議會 COUNCIL]。\n"
                f"════════════════════════════════════════════════\n"
            )
        else:
            return (
                f"\n\n════════ [PIPELINE EXECUTION: single_llm] ════════\n"
                f"你係 single-LLM environment 內 simulated trinity 嘅一部分。\n"
                f"按 prompt 既定 instructions 處理（legacy 4-block 模式可保留）。\n"
                f"════════════════════════════════════════════════\n"
            )

    def _extract_voice_block(self, text: str, role: str) -> str:
        """Defensive parser: extract only role's voice block from possibly 4-block output.

        If text contains FATHER/SON/SPIRIT/COUNCIL markers and role's block is identifiable,
        return only role's block. Otherwise return text as-is.

        role: "father" / "son" / "spirit"
        """
        if role not in ("father", "son", "spirit"):
            return text
        # Voice block headers (handle both [聖父 FATHER] and [FATHER] variants)
        role_markers = {
            "father": ["[聖父 FATHER]", "[FATHER]", "[聖父", "聖父 FATHER"],
            "son":    ["[聖子 SON]", "[SON]", "[聖子", "聖子 SON"],
            "spirit": ["[聖靈 SPIRIT]", "[SPIRIT]", "[聖靈", "聖靈 SPIRIT"],
        }
        other_markers = []
        for other_role, markers in role_markers.items():
            if other_role != role:
                other_markers.extend(markers)
        # Also stop at council / response markers
        other_markers.extend([
            "[議會 COUNCIL]", "[COUNCIL]", "[議會",
            "[回應 RESPONSE]", "[RESPONSE]", "[回應",
        ])

        # Find first marker for this role
        my_markers = role_markers[role]
        start_pos = -1
        my_marker_used = None
        for m in my_markers:
            idx = text.find(m)
            if idx >= 0 and (start_pos < 0 or idx < start_pos):
                start_pos = idx
                my_marker_used = m
        if start_pos < 0:
            # No marker found — text might already be voice-only without header
            return text.strip()

        # Find earliest "other" marker AFTER start_pos
        end_pos = len(text)
        for m in other_markers:
            idx = text.find(m, start_pos + len(my_marker_used))
            if idx >= 0 and idx < end_pos:
                end_pos = idx

        # Also stop at (0,0,0). footer
        footer = text.find("(0,0,0).", start_pos)
        if footer >= 0 and footer < end_pos:
            end_pos = footer + len("(0,0,0).")

        return text[start_pos:end_pos].strip()

    # ═══════════════════════════════════════════════════════════════
    # Auto-tool agent (chat-native tool invocation)
    # ═══════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════
    # Phase 3 Fix-1: Dynamic custom tool registry (auto-tool agent integration)
    # ═══════════════════════════════════════════════════════════════

    # Module-level cache of (tools_active_dir_mtime, [tool_specs])
    _custom_tools_cache: Tuple[float, List[Dict]] = (0.0, [])

    def _load_active_custom_tools(self) -> List[Dict]:
        """Scan tools/active/*.py, dynamic-import each, extract metadata.

        Returns list of dicts: {name, method, params_schema, description, module_name, mtime}.
        Cached by directory mtime — invalidates when files added/removed/edited.

        ⚠ Pitfalls handled:
          - importlib cache: use importlib.invalidate_caches() before each scan
          - re-import after edit: pass spec.loader.exec_module() against fresh module
          - syntax error / missing constants: log + skip, do NOT poison registry
        """
        import importlib, importlib.util
        active_dir = Path(__file__).parent / "tools" / "active"
        if not active_dir.is_dir():
            self.__class__._custom_tools_cache = (0.0, [])
            return []
        # mtime watermark across all files + dir
        try:
            dir_mtime = active_dir.stat().st_mtime
        except OSError:
            return []
        file_mtimes = [dir_mtime]
        py_files = []
        for f in active_dir.glob("*.py"):
            if f.stem == "__init__":
                continue
            try:
                file_mtimes.append(f.stat().st_mtime)
                py_files.append(f)
            except OSError:
                continue
        watermark = max(file_mtimes) if file_mtimes else 0.0

        cached_mtime, cached_specs = self.__class__._custom_tools_cache
        if cached_mtime == watermark and cached_specs:
            return cached_specs

        # Re-scan: importlib invalidate then load each
        importlib.invalidate_caches()
        specs = []
        for f in py_files:
            mod_qualname = f"_uruk_active_{f.stem}"
            # Drop any stale import of this module
            import sys as _sys
            if mod_qualname in _sys.modules:
                del _sys.modules[mod_qualname]
            try:
                spec = importlib.util.spec_from_file_location(mod_qualname, f)
                if not spec or not spec.loader:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                # Log + skip (don\'t poison registry)
                print(f"[custom_tools] skip {f.name}: {type(e).__name__}: {e}", file=__import__("sys").stderr)
                continue
            tool_name = getattr(mod, "TOOL_NAME", None)
            tool_method = getattr(mod, "TOOL_METHOD", None)
            params_schema = getattr(mod, "TOOL_PARAMS_SCHEMA", {}) or {}
            if not tool_name or not tool_method:
                print(f"[custom_tools] skip {f.name}: missing TOOL_NAME/TOOL_METHOD", file=__import__("sys").stderr)
                continue
            # Description: module docstring OR docstring of entry fn OR fallback
            description = (mod.__doc__ or "").strip()
            if not description:
                fn = getattr(mod, tool_method, None)
                if fn and fn.__doc__:
                    description = fn.__doc__.strip()
            if not description:
                description = f"Custom tool {tool_name} (no description)"
            # Trim description to 1 line for prompt brevity
            description = description.split("\n", 1)[0].strip()
            if len(description) > 200:
                description = description[:200] + "..."
            specs.append({
                "name": tool_name,
                "method": tool_method,
                "params_schema": params_schema if isinstance(params_schema, dict) else {},
                "description": description,
                "module": mod,
                "file_mtime": f.stat().st_mtime,
            })
        self.__class__._custom_tools_cache = (watermark, specs)
        return specs

    def _build_tool_agent_prompt(self) -> str:
        """Build TOOL_AGENT_SYSTEM_PROMPT with dynamic custom tools section."""
        custom_tools = self._load_active_custom_tools()
        base = self.TOOL_AGENT_SYSTEM_PROMPT_BASE
        if not custom_tools:
            # No custom tools — append empty section for prompt stability
            return base + "\n\n=== Custom tools（操作者 promote 嘅）===\n（暫無 custom tools。response 入面 custom_tools 留 empty list）"
        lines = ["", "", "=== Custom tools（操作者 promote 嘅）===", ""]
        for t in custom_tools:
            lines.append(f"- **{t['name']}**: {t['description']}")
            ps = t['params_schema']
            if ps:
                params_brief = ", ".join(
                    f"{k}({v.get('type','any')}{', required' if v.get('required') else ''})"
                    for k, v in ps.items() if isinstance(v, dict)
                )
                lines.append(f"  params: {{{params_brief}}}")
            else:
                lines.append(f"  params: {{}} (無參數)")
        lines.append("")
        lines.append("如 user input 需要某個 custom tool，response 嘅 `custom_tools` field append:")
        lines.append("  {\"name\": \"<tool_name>\", \"params\": {<args>}}")
        lines.append("可 invoke 多個 custom tools（list 入面多個 entry）。")
        lines.append("Default: custom_tools 留 [] empty list（保守原則同 search 一致）。")
        return base + "\n".join(lines)

    TOOL_AGENT_SYSTEM_PROMPT_BASE = """你係 tool decision agent。Analyze user input，decide 要唔要 invoke 以下 tools。

只返 JSON，唔好加任何其他文字、preamble、markdown fence：

{
  "search": {"needed": false, "query": ""},
  "fetch": {"needed": false, "url": ""},
  "calendar": {"needed": false, "from": "", "to": ""},
  "custom_tools": []
}

決策規則：

✓ search.needed = true 當：
  - 用戶問 factual external info（例：「What is Landauer's principle?」/「Tell me about X」/「最近 X 嘅 news」）
  - User explicit ask 要外部資料 / latest info
  query field：揀 2-5 個 keywords 嘅最有效搜索字串（英文 OK if topic 國際性，中文 OK if 香港/local topic）

✓ fetch.needed = true 當：
  - 用戶明確 paste 一個 URL（例：「睇下 https://example.com 講咩」/「Read this: https://...」）
  url field：完整 URL（包括 https://）

✓ calendar.needed = true 當：
  - 用戶問自己 schedule（例：「我聽日有咩 meeting?」「下星期幾號有 event?」）
  from / to：YYYY-MM-DD format

✓ custom_tools = [{name, params}, ...] 當：
  - User input 內容明顯 match 下面其中一個 custom tool 嘅描述
  - 揀 most specific match。可 invoke 多個如 input 需要

保守原則：
- 純哲學 / 心理 / 個人 reflection / abstract reasoning → 全部 false / empty
- 唔確定 → 全部 false / empty（lower friction default）
- 「點解 X」「我點樣 Y」嘅 question 通常 false（內部 reasoning，唔需要外部資料）

每個 field 都必須出現喺 JSON。唔需要嘅 tool 將 needed 設 false + 對應 query/url 設 ""，custom_tools 留 []。"""

    # Backward-compat alias for any code still referencing static prompt.
    # Note: callers should use _build_tool_agent_prompt() for dynamic section.
    TOOL_AGENT_SYSTEM_PROMPT = TOOL_AGENT_SYSTEM_PROMPT_BASE

    async def _tool_agent_decide(self, user_input: str) -> Dict:
        """Run tool agent LLM call to decide which (if any) tools to invoke.

        Uses dispatcher node (cheap + fast). Returns structured decision dict.
        Defaults to all-false on any error (fail-safe — no tool invocation).
        """
        FALLBACK = {
            "search":   {"needed": False, "query": ""},
            "fetch":    {"needed": False, "url": ""},
            "calendar": {"needed": False, "from": "", "to": ""},
            "custom_tools": [],
        }
        node_cfg = self.nodes.get("dispatcher")
        if not node_cfg:
            return FALLBACK
        adapter_cls = ADAPTERS.get(node_cfg.provider)
        if adapter_cls is None:
            return FALLBACK
        api_key = os.environ.get(node_cfg.api_key_env) if node_cfg.api_key_env else None
        if node_cfg.provider != "ollama" and not api_key:
            return FALLBACK

        adapter = adapter_cls(api_key=api_key, api_base=node_cfg.api_base)
        # Build dynamic prompt with custom tools registry
        system_prompt = self._build_tool_agent_prompt()
        # Bump max_tokens 200→800 to accommodate custom_tools list + thinking budget
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        try:
            raw = await adapter.call(
                messages=messages,
                model=node_cfg.model,
                temperature=0.1,
                max_tokens=800,
            )
        except Exception:
            return FALLBACK

        # Parse JSON (v8.14 P5 lenient extraction)
        try:
            decision = self._extract_json_lenient(raw)
        except (json.JSONDecodeError, ValueError):
            return FALLBACK

        # Normalize structure (in case LLM omits fields)
        for k in ("search", "fetch", "calendar"):
            if k not in decision or not isinstance(decision[k], dict):
                decision[k] = FALLBACK[k]
            else:
                decision[k].setdefault("needed", False)
                decision[k].setdefault("query" if k == "search" else ("url" if k == "fetch" else "from"), "")
                if k == "calendar":
                    decision[k].setdefault("to", "")
        # Normalize custom_tools: must be a list of {name, params} dicts
        ct = decision.get("custom_tools")
        if not isinstance(ct, list):
            decision["custom_tools"] = []
        else:
            # Filter invalid entries + verify names against registry
            valid_names = {t["name"] for t in self._load_active_custom_tools()}
            cleaned_ct = []
            for entry in ct:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name", "").strip()
                params = entry.get("params", {})
                if not name or name not in valid_names:
                    continue  # silently drop hallucinated tool names
                if not isinstance(params, dict):
                    params = {}
                cleaned_ct.append({"name": name, "params": params})
            decision["custom_tools"] = cleaned_ct
        return decision

    async def _execute_tools(self, decisions: Dict) -> str:
        """Execute requested tools, return formatted result string (or empty)."""
        if not decisions:
            return ""
        parts = []

        # Search
        try:
            if decisions.get("search", {}).get("needed"):
                from browser_service import browser
                q = decisions["search"].get("query", "").strip()
                if q:
                    try:
                        results = await browser.web_search(q, n=5)
                        if results:
                            block = f"📎 [Auto Tool · Web Search: \"{q}\"]\n"
                            for i, r in enumerate(results, 1):
                                block += f"{i}. {r['title']} — {r['url']}\n"
                            parts.append(block)
                    except Exception as e:
                        parts.append(f"📎 [Auto Tool · Search failed: {e}]")
        except ImportError:
            pass

        # Fetch
        try:
            if decisions.get("fetch", {}).get("needed"):
                from browser_service import browser
                url = decisions["fetch"].get("url", "").strip()
                if url:
                    try:
                        data = await browser.fetch_url(url)
                        snippet = data.get("main_text", "")[:2000]
                        block = (
                            f"📎 [Auto Tool · Fetched: {data.get('final_url', url)}]\n"
                            f"Title: {data.get('title', '(no title)')}\n"
                            f"Date: {data.get('date_published') or '?'}\n"
                            f"=== Main text (first 2K chars) ===\n{snippet}\n=== END ===\n"
                        )
                        parts.append(block)
                    except Exception as e:
                        parts.append(f"📎 [Auto Tool · Fetch failed: {e}]")
        except ImportError:
            pass

        # Calendar
        try:
            if decisions.get("calendar", {}).get("needed"):
                from calendar_service import calendar_svc
                cal = decisions["calendar"]
                # Pick first .ics file if user doesn't specify (no file selection in tool agent)
                files = calendar_svc.list_files()
                if files:
                    fname = files[0]["filename"]
                    try:
                        events = calendar_svc.list_events(
                            fname,
                            from_dt=cal.get("from") or None,
                            to_dt=cal.get("to") or None,
                            limit=20,
                        )
                        if events:
                            block = f"📎 [Auto Tool · Calendar: {fname} {cal.get('from','?')} → {cal.get('to','?')}]\n"
                            for i, ev in enumerate(events, 1):
                                block += f"{i}. {ev['summary']}  [{ev.get('start','?')}]"
                                if ev.get("location"):
                                    block += f"  @ {ev['location']}"
                                block += "\n"
                            parts.append(block)
                        else:
                            parts.append(f"📎 [Auto Tool · Calendar: 冇符合條件嘅 event 喺 {fname}]")
                    except Exception as e:
                        parts.append(f"📎 [Auto Tool · Calendar failed: {e}]")
                else:
                    parts.append("📎 [Auto Tool · Calendar: 冇 .ics file 喺 data/calendar/]")
        except ImportError:
            pass

        # ─── Custom tools (Phase 3 Fix-1) ───
        custom_tools_decisions = decisions.get("custom_tools") or []
        if custom_tools_decisions:
            registry = {t["name"]: t for t in self._load_active_custom_tools()}
            for entry in custom_tools_decisions:
                name = entry.get("name", "")
                params = entry.get("params", {}) or {}
                spec = registry.get(name)
                if not spec:
                    parts.append(f"📎 [Auto Tool · Custom: 「{name}」唔喺 active registry]")
                    continue
                try:
                    mod = spec["module"]
                    method_name = spec["method"]
                    if hasattr(mod, "SERVICE"):
                        fn = getattr(mod.SERVICE, method_name, None)
                        result = fn(**params) if fn else None
                    else:
                        fn = getattr(mod, method_name, None)
                        result = fn(params) if fn else None
                    if result is None:
                        parts.append(f"📎 [Auto Tool · Custom 「{name}」: entry function 未揾到]")
                        continue
                    pretty = json.dumps(result, ensure_ascii=False, indent=2)
                    # Trim if too long
                    if len(pretty) > 3000:
                        pretty = pretty[:3000] + "\n... (truncated)"
                    parts.append(f"📎 [Auto Tool · Custom: {name}(params={params})]\n{pretty}")
                except Exception as e:
                    parts.append(f"📎 [Auto Tool · Custom 「{name}」failed: {type(e).__name__}: {e}]")

        return "\n".join(parts)

    # ═══════════════════════════════════════════════════════════════
    # Skill Registry integration (Phase 1)
    # ═══════════════════════════════════════════════════════════════

    SKILL_MATCH_SYSTEM_PROMPT = """你係 skill matcher。User input 加 skill trigger_cue list，揾邊個（如有）match。

返 JSON only，唔好加任何其他文字：

{
  "matched": ["<skill name>", ...],   // 0 或多個。如全部唔 match，返 []
  "rationale": "<one short sentence>"  // 點解 match / 點解唔 match
}

保守原則：除非 user input 強烈 semantic match trigger_cue，default 返 [] (空 list)。
如多於 1 個 match，按 most specific to least specific 排序。
"""

    META_COMMAND_PATTERNS = [
        # (pattern_regex, action, capture_group_idx)
        # ── v8.2: /echo for stress testing — short-circuits the pipeline ──
        # Bypasses all LLM calls. Used by browser stress runner to exercise
        # FastAPI / SSE / pipeline counter under load without burning quota.
        (r"^\s*/echo\b\s*(.*)$", "echo", 1),
        # ── v8.2: /skill <name> [input] — directly invoke a named skill ──
        # Bypasses LLM-based skill matching (_match_skills) to stress test
        # skill_registry lookup + _apply_matched_skill + tool dispatch path.
        # Group 1 captures "<name> [optional input]" — handler splits on first space.
        (r"^\s*/skill\s+(.+?)\s*$", "invoke_skill", 1),
        # ── Phase 3: TOOL author commands (must come first — own keyword 'tool') ──
        (r"^\s*(?:我想|想)?\s*(?:加|create|新增|加個|加一個)\s*(?:個|一個)?\s*tool\s*[:：]\s*(.+?)\s*$", "create_tool", 1),
        (r"^\s*(?:promote|啟用|升)\s+tool\s+(.+?)\s*$", "promote_tool", 1),
        (r"^\s*(?:unpromote|降|停用)\s+tool\s+(.+?)\s*$", "unpromote_tool", 1),
        (r"^\s*(?:cancel\s+tool|cancel-tool|取消\s*tool)\s*$", "cancel_tool", None),
        (r"^\s*(?:run|跑|執行)\s+tool\s+(\w+)(?:\s+(?:with\s+)?(.+?))?\s*$", "run_tool", 1),
        (r"^\s*(?:list|show)?\s*(?:我有咩|有咩|乜嘢)?\s*(?:tools|工具)\s*[?？]?\s*$", "list_tools", None),
        # ── Phase 2: skill CREATION (must come first to win over generic enable/disable) ──
        # create — user describes desired skill
        (r"^\s*(?:我想|想)?\s*(?:加|create|新增|加個|加一個)\s*(?:個|一個)?\s*skill\s*[:：]\s*(.+?)\s*$", "create_skill", 1),
        # confirm pending draft
        (r"^\s*(?:ok|OK|繼續|save|係|yes|確認|存)\s*[!！。.]?\s*$", "confirm_skill", None),
        # refine pending draft with feedback
        (r"^\s*(?:改|edit|update|修改)\s*[:：]?\s*(.+?)\s*$", "refine_skill", 1),
        # cancel pending draft
        (r"^\s*(?:cancel|算啦|唔好|算數|drop)\s*$", "cancel_skill", None),

        # ── Phase 1: skill list / toggle / describe ──
        (r"^\s*(?:list|show)?\s*(?:我有咩|有咩|乜嘢|edges|skills|技能|skill)\s*(?:有|可以用|enabled|skills?)?\s*[?？]?\s*$", "list_skills", None),
        (r"^\s*(?:啟用|開啟)\s*(.+?)\s*$", "enable_skill", 1),
        (r"^\s*(?:enable|on)\s+(.+?)\s*$", "enable_skill", 1),
        (r"^\s*(?:關咗|關掉|停咗|停用)\s*(.+?)\s*$", "disable_skill", 1),
        (r"^\s*(?:disable|stop|off)\s+(.+?)\s*$", "disable_skill", 1),
        (r"^\s*skill\s+(.+?)\s+(?:係咩|講咩|描述|describe|info)\s*[?？]?\s*$", "describe_skill", 1),
    ]

    def _detect_meta_command(self, user_input: str) -> Optional[Dict]:
        """Detect chat meta commands. Returns {action, arg} or None."""
        text = user_input.strip()
        # Phase 3: pending tool clarification intercept (state-based routing)
        # If operator is mid-tool-clarify, route any non-cancel input as clarify-answer.
        # Length limit lifted because clarification answers can be long.
        if self._pending_tool_user_desc and self._pending_tool_clarifications and not self._pending_tool_code:
            head = text[:200]
            if re.match(r"^\s*(?:cancel\s+tool|cancel-tool|取消\s*tool|算啦\s*tool)\s*$", head, re.IGNORECASE):
                return {"action": "cancel_tool", "arg": None, "raw": text}
            return {"action": "tool_clarify_answer", "arg": text, "raw": text}
        if len(text) > 200:  # too long, treat as normal input
            return None
        for pattern, action, group_idx in self.META_COMMAND_PATTERNS:
            m = re.match(pattern, text, re.IGNORECASE)
            if m:
                arg = m.group(group_idx).strip() if group_idx else None
                return {"action": action, "arg": arg, "raw": text}
        return None

    def _handle_meta_command(self, cmd: Dict) -> str:
        """Execute meta command, return user-facing reply text."""
        from skill_registry import skill_registry
        action = cmd["action"]

        # ── v8.2: /echo — minimal short-circuit for stress test ──
        if action == "echo":
            arg = (cmd.get("arg") or "").strip()
            return f"🔁 echo: {arg}" if arg else "🔁 echo: (empty)"

        if action == "list_skills":
            skills = skill_registry.list_skills()
            if not skills:
                return "🧩 而家冇 skill。可以打『我想加個 skill：...』 chat-create。"
            lines = ["🧩 **可用 skills：**", ""]
            for s in skills:
                status = "✓ 啟用" if s["enabled"] else "✗ 關咗"
                badge = "[builtin]" if s["source"] == "builtin" else "[user]"
                lines.append(f"  {status}  **{s['name']}** {badge}")
                lines.append(f"         {s['description']}")
                lines.append(f"         觸發：{s['trigger_cue']}")
                lines.append("")
            lines.append("Commands：『啟用 X』 / 『關咗 X』 / 『skill X 講咩?』")
            return "\n".join(lines)

        if action == "enable_skill":
            name = cmd["arg"]
            ok = skill_registry.toggle_skill(name, True)
            return f"✓ 已啟用「{name}」" if ok else f"✗ 揾唔到「{name}」(用「list skills」睇可用)"

        if action == "disable_skill":
            name = cmd["arg"]
            ok = skill_registry.toggle_skill(name, False)
            return f"✓ 已關咗「{name}」" if ok else f"✗ 揾唔到「{name}」"

        if action == "describe_skill":
            name = cmd["arg"]
            s = skill_registry.get_skill(name)
            if not s:
                return f"✗ 揾唔到「{name}」"
            lines = [
                f"🧩 **{s['name']}**  [{s['source']}]  {'✓ 啟用' if s.get('enabled') else '✗ 關咗'}",
                f"",
                f"**描述**：{s.get('description', '')}",
                f"**觸發**：{s.get('trigger_cue', '')}",
                f"**Action type**：{s.get('action_type', 'prompt_template')}",
            ]
            if s.get("action_type") == "prompt_template":
                lines.append(f"")
                lines.append(f"**Prompt template**：")
                lines.append(f"```")
                lines.append(s.get("prompt_template", "")[:500])
                lines.append(f"```")
            else:
                lines.append(f"")
                lines.append(f"**Tool calls**：")
                for tc in s.get("tool_calls", []):
                    lines.append(f"  - tool: {tc.get('tool')}, params: {tc.get('params')}")
            return "\n".join(lines)

        # Phase 2: sync actions (confirm / cancel — no LLM call)
        if action == "confirm_skill":
            return self._handle_skill_confirm()
        if action == "cancel_skill":
            return self._handle_skill_cancel()

        # Phase 3: tool sync actions (no LLM call)
        if action == "list_tools":
            return self._handle_tool_list()
        if action == "promote_tool":
            return self._handle_tool_promote(cmd["arg"])
        if action == "unpromote_tool":
            return self._handle_tool_unpromote(cmd["arg"])
        if action == "cancel_tool":
            return self._handle_tool_cancel()
        if action == "run_tool":
            return self._handle_tool_run(cmd["arg"], cmd.get("raw", ""))

        # Phase 2: async actions require async wrapper (handled separately in app.py)
        # If we reach here for create_skill / refine_skill / create_tool / tool_clarify_answer,
        # indicates routing mismatch
        if action in ("create_skill", "refine_skill", "create_tool", "tool_clarify_answer"):
            return "⚠ Internal: async action mis-routed. Should use _handle_meta_command_async."

        return f"⚠ 未知 meta command: {action}"

    async def _handle_meta_command_async(self, cmd: Dict) -> str:
        """Async version for skill creation / refinement (require LLM call).

        For sync actions (list / toggle / describe / confirm / cancel), delegates to sync handler.
        """
        action = cmd["action"]
        # v8.2: direct skill invoke for stress testing — runs apply path without LLM matching
        if action == "invoke_skill":
            return await self._handle_invoke_skill(cmd.get("arg") or "")
        # Phase 3: tool async actions
        if action == "create_tool":
            return await self._handle_tool_creation(cmd["arg"])
        if action == "tool_clarify_answer":
            return await self._handle_tool_clarification_done(cmd["arg"])
        if action == "create_skill":
            return await self._handle_skill_creation(cmd["arg"])
        if action == "refine_skill":
            # Refinement only valid if there's pending draft AND feedback
            if not self._pending_skill_draft:
                # Not a skill refinement context — could be unrelated 「改 ...」
                # Pass through as if not meta command
                return "❌ 冇 pending skill draft 可以「改」。如果想改 protocol 文件，用 file editor。如果想 create skill 先「我想加個 skill：...」。"
            return await self._handle_skill_refine(cmd["arg"])
        # Sync actions go through sync handler
        return self._handle_meta_command(cmd)

    async def _match_skills(self, user_input: str) -> List[Dict]:
        """LLM-based skill matching. Returns list of matched skill defs (sorted by specificity)."""
        from skill_registry import skill_registry
        enabled = skill_registry.list_skills(enabled_only=True)
        if not enabled:
            return []

        # Build cue list for LLM
        cue_lines = []
        for s in enabled:
            cue_lines.append(f"- {s['name']}: {s['trigger_cue']}")
        cue_block = "\n".join(cue_lines)

        node_cfg = self.nodes.get("dispatcher")
        if not node_cfg:
            return []
        adapter_cls = ADAPTERS.get(node_cfg.provider)
        if adapter_cls is None:
            return []
        api_key = os.environ.get(node_cfg.api_key_env) if node_cfg.api_key_env else None
        if node_cfg.provider != "ollama" and not api_key:
            return []

        adapter = adapter_cls(api_key=api_key, api_base=node_cfg.api_base)
        user_content = f"User input:\n{user_input}\n\nAvailable skill cues:\n{cue_block}"
        messages = [
            {"role": "system", "content": self.SKILL_MATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            raw = await adapter.call(
                messages=messages,
                model=node_cfg.model,
                temperature=0.1,
                max_tokens=200,
            )
        except Exception:
            return []

        try:
            decision = self._extract_json_lenient(raw)
            matched_names = decision.get("matched", [])
        except (json.JSONDecodeError, ValueError):
            return []

        if not matched_names:
            return []

        matched_skills = []
        for name in matched_names:
            s = skill_registry.get_skill(name)
            if s and s.get("enabled"):
                matched_skills.append(s)
        return matched_skills

    async def _apply_matched_skill(self, skill: Dict, user_input: str) -> Dict:
        """Apply skill action. For tool_call, execute tools and return formatted result.

        Returns: {
          'skill_name': str,
          'type': 'prompt_template' | 'tool_call',
          'injection': str,         # text to append to user_input
          'tool_calls_invoked': list,
        }
        """
        from skill_registry import skill_registry
        applied = skill_registry.apply_skill(skill, user_input)
        injection_parts = []
        tool_invocations = []

        if applied["type"] == "tool_call":
            tool_results_text = []
            for tc in applied["tool_calls"]:
                tool = tc["tool"]
                params = tc["params"]
                try:
                    if tool == "web_search":
                        from browser_service import browser
                        results = await browser.web_search(params.get("query", ""), n=int(params.get("n", 5)))
                        block_lines = [f"📎 [Skill「{skill['name']}」· web_search: \"{params.get('query','')}\"]"]
                        for i, r in enumerate(results, 1):
                            block_lines.append(f"{i}. {r['title']} — {r['url']}")
                        tool_results_text.append("\n".join(block_lines))
                        tool_invocations.append({"tool": tool, "params": params, "result_count": len(results)})
                    elif tool == "fetch_url":
                        from browser_service import browser
                        url = params.get("url", "")
                        if url:
                            data = await browser.fetch_url(url)
                            snippet = data.get("main_text", "")[:2000]
                            block = (
                                f"📎 [Skill「{skill['name']}」· fetch_url: {data.get('final_url', url)}]\n"
                                f"Title: {data.get('title', '(no title)')}\n"
                                f"=== Main text (first 2K chars) ===\n{snippet}\n=== END ===\n"
                            )
                            tool_results_text.append(block)
                            tool_invocations.append({"tool": tool, "params": params, "size": data.get("size_bytes")})
                    elif tool == "calendar":
                        from calendar_service import calendar_svc
                        files = calendar_svc.list_files()
                        if files:
                            fname = files[0]["filename"]
                            events = calendar_svc.list_events(
                                fname,
                                from_dt=params.get("from_dt") or None,
                                to_dt=params.get("to_dt") or None,
                                limit=20,
                            )
                            block_lines = [f"📎 [Skill「{skill['name']}」· calendar: {fname} {params.get('from_dt','?')}→{params.get('to_dt','?')}]"]
                            for i, ev in enumerate(events, 1):
                                line = f"{i}. {ev['summary']}  [{ev.get('start','?')}]"
                                if ev.get("location"):
                                    line += f"  @ {ev['location']}"
                                block_lines.append(line)
                            tool_results_text.append("\n".join(block_lines))
                            tool_invocations.append({"tool": tool, "params": params, "event_count": len(events)})
                        else:
                            tool_results_text.append(f"📎 [Skill「{skill['name']}」· calendar: 冇 .ics 喺 data/calendar/]")
                    elif tool == "stress_echo":
                        # v8.2: no-op tool for stress testing skill+tool dispatch.
                        # Returns rendered params verbatim. No network, no LLM, no I/O.
                        msg = params.get("message", "")
                        if len(msg) > 500:
                            msg = msg[:500] + "..."
                        tool_results_text.append(f"📎 [Skill「{skill['name']}」· stress_echo: {msg}]")
                        tool_invocations.append({"tool": tool, "params": params, "echoed_len": len(str(msg))})
                    else:
                        # Phase 3 Fix-2: dispatch custom tool by name
                        registry = {t["name"]: t for t in self._load_active_custom_tools()}
                        spec = registry.get(tool)
                        if spec:
                            mod = spec["module"]
                            method_name = spec["method"]
                            if hasattr(mod, "SERVICE"):
                                fn = getattr(mod.SERVICE, method_name, None)
                                result = fn(**(params or {})) if fn else None
                            else:
                                fn = getattr(mod, method_name, None)
                                result = fn(params or {}) if fn else None
                            if result is None:
                                tool_results_text.append(f"📎 [Skill「{skill['name']}」· custom {tool}: entry fn missing]")
                                tool_invocations.append({"tool": tool, "error": "entry function missing"})
                            else:
                                pretty = json.dumps(result, ensure_ascii=False, indent=2)
                                if len(pretty) > 3000:
                                    pretty = pretty[:3000] + "\n... (truncated)"
                                tool_results_text.append(f"📎 [Skill「{skill['name']}」· custom {tool}(params={params})]\n{pretty}")
                                tool_invocations.append({"tool": tool, "params": params, "result_type": type(result).__name__})
                        else:
                            tool_results_text.append(f"📎 [Skill「{skill['name']}」· unknown tool {tool!r} — not in registry]")
                            tool_invocations.append({"tool": tool, "error": "not in active registry"})
                except Exception as e:
                    tool_results_text.append(f"📎 [Skill「{skill['name']}」· {tool} failed: {e}]")
                    tool_invocations.append({"tool": tool, "error": str(e)})

            joined_tool_text = "\n\n".join(tool_results_text)
            # Render prompt_template with tool_results substitution
            tmpl = applied.get("rendered_prompt", "")
            if tmpl:
                rendered = tmpl.replace("{{tool_results}}", joined_tool_text)
                rendered = rendered.replace("{{tool_count}}", str(len(applied["tool_calls"])))
                injection_parts.append(f"━━ Skill「{skill['name']}」 applied ━━\n{rendered}")
            else:
                injection_parts.append(joined_tool_text)
        else:
            # prompt_template only
            injection_parts.append(f"━━ Skill「{skill['name']}」 applied ━━\n{applied['rendered_prompt']}")

        return {
            "skill_name": skill["name"],
            "type": applied["type"],
            "injection": "\n\n".join(injection_parts),
            "tool_calls_invoked": tool_invocations,
        }

    async def _handle_invoke_skill(self, arg: str) -> str:
        """v8.2: Direct skill invocation by name (bypass LLM matching).

        arg format: "<skill_name> [optional input text]"
        Returns formatted text result (skill injection + tool invocation summary).

        Used primarily for stress testing the skill_registry + _apply_matched_skill
        + tool-dispatch path under load without consuming LLM quota.
        """
        from skill_registry import skill_registry
        raw = (arg or "").strip()
        if not raw:
            return "⚠ /skill 需要 skill name。例：`/skill stress_echo ping`"
        # Resolve skill name — supports names with spaces (e.g. "Calendar audit").
        # Strategy: try the whole arg first; if not a known skill, fall back to
        # progressively shorter prefixes so `/skill Calendar audit ping` resolves
        # name="Calendar audit", input="ping".
        skill = None
        name = raw
        skill_input = ""
        words = raw.split()
        for split_at in range(len(words), 0, -1):
            candidate_name = " ".join(words[:split_at])
            candidate = skill_registry.get_skill(candidate_name)
            if candidate is not None:
                skill = candidate
                name = candidate_name
                skill_input = " ".join(words[split_at:])
                break
        if not skill:
            available = ", ".join(s["name"] for s in skill_registry.list_skills(enabled_only=True))
            return f"⚠ 揾唔到 skill「{raw}」。已啟用：{available or '(冇)'}"
        if not skill.get("enabled"):
            return f"⚠ Skill「{name}」已停用。`啟用 {name}` 再試。"
        try:
            result = await self._apply_matched_skill(skill, skill_input)
        except Exception as e:
            return f"⚠ Skill「{name}」apply 失敗：{type(e).__name__}: {e}"
        tool_summary = ", ".join(
            f"{tc.get('tool')}={'ok' if 'error' not in tc else 'err'}"
            for tc in result.get("tool_calls_invoked", [])
        ) or "no tool calls"
        return (
            f"🧩 Direct-invoked skill「{result['skill_name']}」 ({result['type']})\n"
            f"Tools: {tool_summary}\n\n"
            f"{result['injection']}"
        )

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: Chat-driven skill creation
    # ═══════════════════════════════════════════════════════════════

    SKILL_AUTHOR_SYSTEM_PROMPT = """你係 URUK skill author agent。User 用自然語描述想要嘅 skill，你生成 skill YAML。

返 JSON only，唔好加任何其他文字或 markdown fence：

{
  "name": "<short Cantonese, 4-12 chars, 唔重複 builtin 名>",
  "description": "<one-line clear summary>",
  "trigger_cue": "<semantic description: 用戶咩 phrasing / context 會觸發>",
  "action_type": "prompt_template" OR "tool_call",
  "prompt_template": "<if prompt_template, 用 {{user_input}} placeholder>",
  "tool_calls": [
    {"tool": "web_search", "params": {"query": "{{user_input}} <topic-specific 字眼>", "n": 5}},
    {"tool": "fetch_url", "params": {"url": "{{detected_url}}"}},
    {"tool": "calendar", "params": {"from_dt": "{{today}}", "to_dt": "{{today_plus_7}}"}}
  ],
  "enabled": true,
  "source": "user",
  "created": "<YYYY-MM-DD>"
}

原則：
- prompt_template 適合「要 URUK 用特定 lens 分析」
- tool_call 適合「需要外部資料 / fetch / calendar」
- tool_call 可以同時有 prompt_template (rendered after tool execution，用 {{tool_results}} placeholder)
- 用日常廣東話寫 name / description / trigger_cue
- name 唔可重複 builtin: 睡眠 coach / 新聞快報 / URL 拆解 / Calendar audit

唯一可用 tools: web_search / fetch_url / calendar (其他 reject)

Available template variables in tool params / prompt_template:
- {{user_input}}: 原始 user input
- {{today}}: ISO date 今日
- {{today_plus_7}}: 一週後
- {{tomorrow}}: 聽日
- {{detected_url}}: input 入面 detected URL (for fetch_url skill)
- {{tool_results}}: tool 執行後嘅 results (prompt_template only)
- {{tool_count}}: tool calls 數量
"""

    BUILTIN_SKILL_NAMES = {"睡眠 coach", "新聞快報", "URL 拆解", "Calendar audit"}
    ALLOWED_TOOLS = {"web_search", "fetch_url", "calendar"}

    def _get_allowed_tools(self) -> set:
        """Phase 3 Fix-2: dynamic allowed tools = builtin + active custom tools."""
        custom_names = {t["name"] for t in self._load_active_custom_tools()}
        return self.ALLOWED_TOOLS | custom_names

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: Tool author system prompts (3 LLM agents)
    # ═══════════════════════════════════════════════════════════════
# Phase 3: Tool author system prompts
# These are class attributes on TrinityConsole. Outer string uses '''...''' so we can
# embed """docstring""" examples inside freely.

    TOOL_CLARIFY_SYSTEM_PROMPT = '''你係 URUK Trinity Console 嘅 Tool Author Clarifier。

操作者想加一個新嘅 Python tool service。你嘅工作：問 3-5 條精確問題，
clarify 操作者真正想要嘅嘢，避免 hallucination 一個冇人 ask 嘅 tool。

問題必須 cover：
  1. **數據來源**：邊個 API / endpoint？需要 API key？
  2. **輸入參數**：tool 接受咩 params？type 同必填？
  3. **輸出格式**：return dict 嘅 shape 點樣？
  4. **網絡需求**：要 HTTP 出 outbound？域名 whitelist 範圍？
  5. **限制**：rate limit / timeout / payload size limit？

⚠ 嚴格限制：
- 只能用 stdlib + httpx 出 outbound HTTP
- 唔可以 subprocess / os.system / open() local file（除 stdlib JSON parse）
- 唔可以 eval / exec / dunder access

輸出 JSON 格式（純 JSON，唔好 markdown wrap）：
{"questions": ["問題1?", "問題2?", "問題3?", ...]}

最少 3 條，最多 5 條。每條問題具體可答（唔好「你想點」呢類空泛問題）。
'''

    TOOL_AUTHOR_SYSTEM_PROMPT = '''你係 URUK Trinity Console 嘅 Tool Author。

操作者已經 clarify 咗 tool requirements。你嘅工作：生成 Python tool service source code。

═══════════════ 強制 MANIFEST 結構 ═══════════════

每個 tool source 文件必須包含 module-level constants：

  TOOL_NAME = "joke_fetcher"           # snake_case, [a-z][a-z0-9_]*
  TOOL_METHOD = "tool_run"             # entry function name
  TOOL_PARAMS_SCHEMA = {               # param name → {type, required, default?}
      "category": {"type": "str", "required": False, "default": "any"},
  }

═══════════════ 強制 ENTRY FUNCTION ═══════════════

  def tool_run(params: dict) -> dict:
      \"\"\"Brief docstring describing what this returns.\"\"\"
      ...
      return {"status": "ok", "data": ...}

  必須係 sync function（唔好 async）。
  return value 必須係 JSON-serializable dict。
  錯誤情況 return {"status": "error", "message": "..."}.

═══════════════ 強制限制（4-layer gate 會 enforce）═══════════════

✓ 可以 import: stdlib（json, re, urllib.parse, datetime, math, time）, httpx
✗ 唔可以 import: os, sys, subprocess, importlib, ctypes, socket, pickle, marshal
✗ 唔可以用: eval / exec / compile / __import__ / open / file
✗ 唔可以 access dunder attrs（__class__, __globals__, __subclasses__）
✗ 唔可以 getattr/setattr/delattr with dynamic names

═══════════════ 輸出格式 ═══════════════

純 Python source code，唔好 markdown wrap，唔好解釋 prose。
第一行係 # comment 標題（中文短描述），跟住 imports，跟住 manifest constants，
跟住 helper functions（如有），跟住 tool_run。

整個文件控制喺 200 行以內。
'''

    TOOL_SECURITY_REVIEW_SYSTEM_PROMPT = '''你係 URUK Trinity Console 嘅 Tool Security Reviewer (Layer B)。

你會收到一段 Python tool source code，已經通過 Layer A AST audit（無 forbidden imports/calls）。
你嘅工作：second-pass 識別 SUBTLE 安全風險，譬如：

  1. **Secret leak**：code 內 hard-coded API key / token？
  2. **SSRF**：URL 由 params 直接構造，無 whitelist？
  3. **Path traversal**：file path 用 user input 拼？
  4. **Unbounded resource use**：無 timeout / size limit？
  5. **Side effect**：write to disk / send email / 任何 mutation？
  6. **Logic bomb**：date / count-based 觸發異常行為？
  7. **Data exfiltration**：sending data to unexpected endpoints？

⚠ Trust model：呢段 code 由 LLM 生成，可能 hallucinate 危險 pattern 即使
   AST 通過。你嘅 review 必須 paranoid。

輸出 JSON 格式（純 JSON，唔好 markdown wrap）：
{
  "pass": true | false,
  "concerns": ["concern 1", "concern 2", ...],
  "verdict": "短句總結，例 '安全可 promote' / '有 SSRF 風險建議 reject'"
}

pass=false 即係 reject。任何 concern 屬 critical → pass=false。
minor style issue 唔屬 concern。
'''

    async def _skill_author_create(self, user_description: str, previous_draft: Optional[Dict] = None, feedback: Optional[str] = None) -> Optional[Dict]:
        """LLM call to draft a skill YAML. Returns dict or None on failure.

        If previous_draft provided + feedback, regenerate with refinement.
        """
        node_cfg = self.nodes.get("dispatcher")
        if not node_cfg:
            return None
        adapter_cls = ADAPTERS.get(node_cfg.provider)
        if adapter_cls is None:
            return None
        api_key = os.environ.get(node_cfg.api_key_env) if node_cfg.api_key_env else None
        if node_cfg.provider != "ollama" and not api_key:
            return None

        adapter = adapter_cls(api_key=api_key, api_base=node_cfg.api_base)

        # Build user content (with refinement context if applicable)
        if previous_draft and feedback:
            user_content = (
                f"原 user description: {user_description}\n\n"
                f"上一版 draft:\n{json.dumps(previous_draft, ensure_ascii=False, indent=2)}\n\n"
                f"Feedback 要改：{feedback}\n\n"
                f"請按 feedback regenerate skill JSON。"
            )
        else:
            user_content = f"User description: {user_description}\n\n請生成 skill JSON。"

        messages = [
            {"role": "system", "content": self.SKILL_AUTHOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            raw = await adapter.call(
                messages=messages,
                model=node_cfg.model,
                temperature=0.3,
                max_tokens=800,
            )
        except Exception:
            return None

        try:
            draft = self._extract_json_lenient(raw)
        except (json.JSONDecodeError, ValueError):
            return None

        # Validate
        if not self._validate_skill_draft(draft):
            return None
        # Server-side override — LLM-provided values for these fields are NOT trusted:
        #   - 'created': LLM hallucinates dates (e.g. "2024-07-30" stale); always use server today.
        #   - 'source':  must be "user" for chat-created skills; reject any LLM-claimed origin.
        #   - 'enabled': default True. If LLM set false (unusual), respect only if explicitly boolean.
        from datetime import date
        draft["created"] = date.today().isoformat()  # always today, NOT LLM date
        draft["source"] = "user"                       # always user-source
        # 'enabled' — respect explicit False from LLM (rare), else default True
        if not isinstance(draft.get("enabled"), bool):
            draft["enabled"] = True
        return draft

    def _validate_skill_draft(self, draft: Dict) -> bool:
        """Strict schema validation. Reject if any issue."""
        if not isinstance(draft, dict):
            return False
        # Required fields
        for key in ("name", "description", "trigger_cue", "action_type"):
            if key not in draft or not isinstance(draft[key], str) or not draft[key].strip():
                return False
        name = draft["name"].strip()
        # Length
        if len(name) > 30 or len(name) < 2:
            return False
        # Don't shadow builtin names
        if name in self.BUILTIN_SKILL_NAMES:
            return False
        # Action type
        if draft["action_type"] not in ("prompt_template", "tool_call"):
            return False
        # Action-specific validation
        if draft["action_type"] == "prompt_template":
            if not draft.get("prompt_template") or not isinstance(draft["prompt_template"], str):
                return False
        else:  # tool_call
            tcs = draft.get("tool_calls", [])
            if not isinstance(tcs, list) or not tcs:
                return False
            allowed = self._get_allowed_tools()
            for tc in tcs:
                if not isinstance(tc, dict):
                    return False
                if tc.get("tool") not in allowed:
                    # Stash diagnostic on the draft for retry feedback
                    draft["_validation_error"] = (
                        f"tool「{tc.get('tool')}」唔喺 allowed list. "
                        f"Available: {sorted(allowed)}"
                    )
                    return False
                if not isinstance(tc.get("params", {}), dict):
                    return False
        # No dangerous fields
        for forbidden in ("_filename", "_folder", "exec", "eval", "subprocess", "__import__"):
            if forbidden in draft:
                return False
        return True

    async def _handle_skill_creation(self, user_description: str) -> str:
        """Generate draft, stash in self._pending_skill_draft, return preview."""
        draft = await self._skill_author_create(user_description)
        if not draft:
            return (
                "❌ Skill author agent fail (model unreachable 或者 output schema invalid)。\n"
                "Try：(1) check Gemini API key / quota，(2) 用更具體 description 重試。"
            )
        self._pending_skill_draft = draft
        self._pending_skill_user_desc = user_description
        yaml_preview = yaml.safe_dump(draft, allow_unicode=True, sort_keys=False)
        return (
            f"🧩 **Skill draft 已生成**\n\n"
            f"```yaml\n{yaml_preview}```\n"
            f"要 save 落 `data/skills/user/`？\n"
            f"  • 「ok」 / 「繼續」 / 「save」 → 確認 save\n"
            f"  • 「改 <feedback>」 → 加 feedback regenerate\n"
            f"  • 「cancel」 → drop draft"
        )

    def _handle_skill_confirm(self) -> str:
        """Save pending draft to data/skills/user/."""
        if not self._pending_skill_draft:
            return "❌ 冇 pending draft 可以 confirm。請先「我想加個 skill：...」"
        from skill_registry import skill_registry, SkillRegistryError
        draft = self._pending_skill_draft
        try:
            filename = skill_registry.create_skill(draft)
            self._pending_skill_draft = None
            self._pending_skill_user_desc = None
            return (
                f"✓ Skill 「{draft['name']}」 已 save 落 `data/skills/user/{filename}`，即時可用。\n"
                f"  Trigger cue: {draft.get('trigger_cue', '')[:120]}\n"
                f"  Test：直接打 trigger cue 嘅 phrasing 試吓，或者用「skill {draft['name']} 講咩?」review。"
            )
        except SkillRegistryError as e:
            return f"❌ Save fail: {e}"
        except Exception as e:
            return f"❌ Unexpected error: {e}"

    async def _handle_skill_refine(self, feedback: str) -> str:
        """Regenerate pending draft with feedback."""
        if not self._pending_skill_draft or not self._pending_skill_user_desc:
            return "❌ 冇 pending draft 可以改。請先「我想加個 skill：...」"
        new_draft = await self._skill_author_create(
            self._pending_skill_user_desc,
            previous_draft=self._pending_skill_draft,
            feedback=feedback,
        )
        if not new_draft:
            return "❌ Refinement fail。Pending draft 維持原狀，可再試「改 ...」或「ok」save 原 draft。"
        self._pending_skill_draft = new_draft
        yaml_preview = yaml.safe_dump(new_draft, allow_unicode=True, sort_keys=False)
        return (
            f"🧩 **Refined draft**（feedback: {feedback[:80]}）：\n\n"
            f"```yaml\n{yaml_preview}```\n"
            f"  • 「ok」 → save\n"
            f"  • 「改 ...」 → 再 refine\n"
            f"  • 「cancel」 → drop"
        )

    def _handle_skill_cancel(self) -> str:
        """Drop pending draft."""
        if not self._pending_skill_draft:
            return "(冇 pending draft，已經 clear。)"
        name = self._pending_skill_draft.get("name", "(unnamed)")
        self._pending_skill_draft = None
        self._pending_skill_user_desc = None
        return f"✓ Draft「{name}」 已 cancel，未 save 落 disk。"

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: Tool author flow (clarify → author → 4-layer gate → sandbox → promote)
    # ═══════════════════════════════════════════════════════════════

    def _reset_pending_tool(self) -> None:
        """Clear all pending tool state attrs."""
        self._pending_tool_user_desc = None
        self._pending_tool_clarifications = None
        self._pending_tool_answers = None
        self._pending_tool_code = None
        self._pending_tool_meta = None

    async def _tool_author_clarify(self, user_desc: str) -> Optional[List[str]]:
        """LLM call: ask 3-5 clarifying questions about the tool. Returns list or None.

        Sets self._last_tool_agent_error to a diagnostic string on failure (str | None).
        """
        self._last_tool_agent_error = None
        node_cfg = self.nodes.get("dispatcher")
        if not node_cfg:
            self._last_tool_agent_error = "dispatcher node config missing"
            return None
        adapter_cls = ADAPTERS.get(node_cfg.provider)
        if adapter_cls is None:
            self._last_tool_agent_error = f"unknown provider: {node_cfg.provider}"
            return None
        api_key = os.environ.get(node_cfg.api_key_env) if node_cfg.api_key_env else None
        if node_cfg.provider != "ollama" and not api_key:
            self._last_tool_agent_error = f"env var {node_cfg.api_key_env} not set"
            return None
        adapter = adapter_cls(api_key=api_key, api_base=node_cfg.api_base)
        messages = [
            {"role": "system", "content": self.TOOL_CLARIFY_SYSTEM_PROMPT},
            {"role": "user", "content": f"操作者想加 tool：{user_desc}\n\n請問 3-5 條 clarifying questions。"},
        ]
        try:
            # Bumped 600 → 2000: Gemini 2.5 flash thinking + Chinese output truncates at 600
            raw = await adapter.call(
                messages=messages,
                model=node_cfg.model,
                temperature=0.4,
                max_tokens=2000,
            )
        except Exception as e:
            self._last_tool_agent_error = f"adapter call failed: {type(e).__name__}: {e}"
            return None
        if not raw or not raw.strip():
            self._last_tool_agent_error = "empty response from model"
            return None
        try:
            data = self._extract_json_lenient(raw)
        except (json.JSONDecodeError, ValueError) as e:
            self._last_tool_agent_error = (
                f"JSON parse failed ({type(e).__name__}: {e}). "
                f"Raw response head (200ch): {raw[:200]!r}"
            )
            return None
        questions = data.get("questions")
        if not isinstance(questions, list):
            self._last_tool_agent_error = f"response missing 'questions' list (got {type(questions).__name__})"
            return None
        if not (3 <= len(questions) <= 5):
            self._last_tool_agent_error = f"expected 3-5 questions, got {len(questions)}"
            return None
        if not all(isinstance(q, str) and q.strip() for q in questions):
            self._last_tool_agent_error = "one or more questions are not non-empty strings"
            return None
        return [q.strip() for q in questions]

    async def _tool_author_create(self, user_desc: str, answers: str) -> Optional[str]:
        """LLM call: generate Python tool source. Returns code str or None."""
        node_cfg = self.nodes.get("dispatcher")
        if not node_cfg:
            return None
        adapter_cls = ADAPTERS.get(node_cfg.provider)
        if adapter_cls is None:
            return None
        api_key = os.environ.get(node_cfg.api_key_env) if node_cfg.api_key_env else None
        if node_cfg.provider != "ollama" and not api_key:
            return None
        adapter = adapter_cls(api_key=api_key, api_base=node_cfg.api_base)
        user_content = (
            f"操作者原 description：{user_desc}\n\n"
            f"Clarification 答覆：\n{answers}\n\n"
            f"請生成完整 Python tool source（純 code，唔好 markdown wrap）。"
        )
        messages = [
            {"role": "system", "content": self.TOOL_AUTHOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            raw = await adapter.call(
                messages=messages,
                model=node_cfg.model,
                temperature=0.2,
                max_tokens=4000,  # Bumped 2500→4000: Gemini thinking + code output is hungry
            )
        except Exception as e:
            self._last_tool_agent_error = f"author adapter call failed: {type(e).__name__}: {e}"
            return None
        if not raw or not raw.strip():
            self._last_tool_agent_error = "author returned empty response"
            return None
        # Strip markdown code fences if present
        code = raw.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            code = "\n".join(lines)
        return code.strip() or None

    async def _tool_security_review(self, code: str, meta: Dict) -> Optional[Dict]:
        """Layer B LLM security review. Returns {pass, concerns, verdict} or None on failure."""
        node_cfg = self.nodes.get("dispatcher")
        if not node_cfg:
            return None
        adapter_cls = ADAPTERS.get(node_cfg.provider)
        if adapter_cls is None:
            return None
        api_key = os.environ.get(node_cfg.api_key_env) if node_cfg.api_key_env else None
        if node_cfg.provider != "ollama" and not api_key:
            return None
        adapter = adapter_cls(api_key=api_key, api_base=node_cfg.api_base)
        user_content = (
            f"Tool name: {meta.get('tool_name')}\n"
            f"Params schema: {json.dumps(meta.get('params_schema') or {}, ensure_ascii=False)}\n\n"
            f"Source code:\n```python\n{code}\n```\n\n"
            f"Review for security risks. Output JSON."
        )
        messages = [
            {"role": "system", "content": self.TOOL_SECURITY_REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            raw = await adapter.call(
                messages=messages,
                model=node_cfg.model,
                temperature=0.2,
                max_tokens=1500,  # Bumped 600→1500: thinking budget + concerns list
            )
        except Exception as e:
            self._last_tool_agent_error = f"review adapter call failed: {type(e).__name__}: {e}"
            return None
        if not raw or not raw.strip():
            self._last_tool_agent_error = "review returned empty response"
            return None
        try:
            data = self._extract_json_lenient(raw)
        except (json.JSONDecodeError, ValueError) as e:
            self._last_tool_agent_error = (
                f"review JSON parse failed ({type(e).__name__}: {e}). "
                f"Raw head: {raw[:200]!r}"
            )
            return None
        if not isinstance(data.get("pass"), bool):
            return None
        if not isinstance(data.get("concerns"), list):
            data["concerns"] = []
        if not isinstance(data.get("verdict"), str):
            data["verdict"] = ""
        return data

    async def _handle_tool_creation(self, user_desc: str) -> str:
        """Step 1: clarify. Stash desc + questions, return question list."""
        if self._pending_tool_user_desc or self._pending_tool_clarifications:
            return (
                "⚠ 已有 pending tool draft。先「cancel tool」清咗佢，或繼續答現有問題。"
            )
        questions = await self._tool_author_clarify(user_desc)
        if not questions:
            err = self._last_tool_agent_error or "unknown"
            return (
                f"❌ Tool clarify agent fail。\n"
                f"診斷: {err}\n\n"
                f"Try: (1) check API key + quota, (2) 用更具體 description 重試。"
            )
        self._pending_tool_user_desc = user_desc
        self._pending_tool_clarifications = questions
        lines = [
            f"🔧 Tool author 開始 — 想加 tool：**{user_desc}**",
            "",
            "請答以下問題（直接打答案，或者「cancel tool」取消）：",
            "",
        ]
        for i, q in enumerate(questions, 1):
            lines.append(f"  {i}. {q}")
        lines.append("")
        lines.append("⚠ 答完後系統會生成 code → 4-layer gate audit。任何 layer fail = reject。")
        return "\n".join(lines)

    async def _handle_tool_clarification_done(self, answers: str) -> str:
        """Step 2-4: author + Layer A AST + Layer B LLM review + Layer C smoke test."""
        if not self._pending_tool_user_desc:
            return "⚠ 冇 pending tool clarification。先用「我想加個 tool：...」開始。"
        from tool_safety import run_static_gates, ast_audit
        self._pending_tool_answers = answers

        # Step 2: author
        code = await self._tool_author_create(self._pending_tool_user_desc, answers)
        if not code:
            err = self._last_tool_agent_error or "unknown"
            self._reset_pending_tool()
            return f"❌ Tool author agent fail。\n診斷: {err}\n\nState reset，請重新開始。"

        # Layer A + Layer C via run_static_gates
        gates = run_static_gates(code)
        if not gates["ast_passed"]:
            self._reset_pending_tool()
            return (
                "❌ **Layer A (AST audit) REJECTED**\n\n"
                "Issues:\n  - " + "\n  - ".join(gates["ast_issues"]) +
                "\n\n生成嘅 code 含 forbidden pattern。State reset。"
            )
        meta = gates["metadata"]
        if not meta:
            self._reset_pending_tool()
            return (
                "❌ **Metadata extraction failed**\n\n"
                "Issues:\n  - " + "\n  - ".join(gates["metadata_issues"]) +
                "\n\nState reset。"
            )

        # Layer B: LLM security review
        review = await self._tool_security_review(code, meta)
        if not review:
            err = self._last_tool_agent_error or "unknown"
            self._reset_pending_tool()
            return f"❌ **Layer B (LLM security review) UNAVAILABLE**\n診斷: {err}\n\nState reset。"
        if not review.get("pass"):
            self._reset_pending_tool()
            return (
                "❌ **Layer B (LLM security review) REJECTED**\n\n"
                f"Verdict: {review.get('verdict')}\n\n"
                "Concerns:\n  - " + "\n  - ".join(review.get("concerns", [])) +
                "\n\nState reset。"
            )

        # Layer C result
        if not gates["smoke_passed"]:
            self._reset_pending_tool()
            return (
                "❌ **Layer C (subprocess smoke test) REJECTED**\n\n"
                f"Output:\n```\n{gates['smoke_output'][:800]}\n```\n\nState reset。"
            )

        # All 3 layers passed — write to sandbox, await Layer D (operator approve)
        from pathlib import Path
        sandbox_dir = Path(__file__).parent / "tools" / "sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        tool_name = meta["tool_name"]
        sandbox_path = sandbox_dir / f"{tool_name}.py"
        sandbox_path.write_text(code, encoding="utf-8")

        self._pending_tool_code = code
        self._pending_tool_meta = meta

        preview = code if len(code) < 1500 else code[:1500] + "\n... (truncated)"
        return (
            f"✓ **3/4 layers PASSED** — Layer A (AST) + B (LLM review) + C (smoke test)\n\n"
            f"🔧 Tool **{tool_name}** 已寫入 `tools/sandbox/{tool_name}.py`\n\n"
            f"**Layer B verdict**：{review.get('verdict')}\n"
            f"**Smoke test**：通過（subprocess 10s timeout 內 return ok）\n\n"
            f"**Generated code preview**：\n```python\n{preview}\n```\n\n"
            f"⚠ **Layer D (operator manual approve)**：\n"
            f"  - 打「promote tool {tool_name}」 → 移去 active，啟用\n"
            f"  - 打「cancel tool」 → 刪 sandbox file，state reset\n"
            f"  - 唔做 = sandbox 保留，但唔會 active"
        )

    def _handle_tool_promote(self, name: str) -> str:
        """Layer D approve: move sandbox/<name>.py → active/<name>.py."""
        import os as _os
        from pathlib import Path
        base = Path(__file__).parent / "tools"
        sandbox_path = base / "sandbox" / f"{name}.py"
        active_path = base / "active" / f"{name}.py"
        if not sandbox_path.exists():
            return f"✗ 揾唔到 sandbox tool「{name}」(`tools/sandbox/{name}.py` 唔存在)"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        if active_path.exists():
            return f"⚠ 「{name}」已經喺 active。先「unpromote tool {name}」再 promote。"
        # Atomic move (os.replace works cross-fs in same volume; falls back to copy+unlink)
        try:
            _os.replace(str(sandbox_path), str(active_path))
        except OSError:
            active_path.write_bytes(sandbox_path.read_bytes())
            try:
                sandbox_path.unlink()
            except OSError:
                pass  # Best-effort cleanup; active is what matters
        if self._pending_tool_meta and self._pending_tool_meta.get("tool_name") == name:
            self._reset_pending_tool()
        return (
            f"✓ **Layer D APPROVED** — tool「{name}」已 promote 去 active\n\n"
            f"`tools/active/{name}.py` 已啟用。Auto-tool agent 將會見到呢個 tool。\n"
            f"想 rollback：打「unpromote tool {name}」"
        )

    def _handle_tool_unpromote(self, name: str) -> str:
        """Reverse promote: move active/<name>.py → sandbox/<name>.py."""
        import os as _os
        from pathlib import Path
        base = Path(__file__).parent / "tools"
        active_path = base / "active" / f"{name}.py"
        sandbox_path = base / "sandbox" / f"{name}.py"
        if not active_path.exists():
            return f"✗ 揾唔到 active tool「{name}」"
        sandbox_path.parent.mkdir(parents=True, exist_ok=True)
        if sandbox_path.exists():
            try:
                sandbox_path.unlink()
            except OSError:
                pass
        try:
            _os.replace(str(active_path), str(sandbox_path))
        except OSError:
            sandbox_path.write_bytes(active_path.read_bytes())
            try:
                active_path.unlink()
            except OSError:
                return f"⚠ Tool「{name}」copied to sandbox but active 刪唔到（fs 限制）"
        return f"✓ Tool「{name}」已降級返 sandbox。Auto-tool agent 唔再見到佢。"

    def _handle_tool_list(self) -> str:
        """List sandbox + active tools."""
        from pathlib import Path
        base = Path(__file__).parent / "tools"
        active_dir = base / "active"
        sandbox_dir = base / "sandbox"
        active = sorted([p.stem for p in active_dir.glob("*.py") if p.stem != "__init__"]) if active_dir.exists() else []
        sandbox = sorted([p.stem for p in sandbox_dir.glob("*.py") if p.stem != "__init__"]) if sandbox_dir.exists() else []
        lines = ["🔧 **Custom tools：**", ""]
        lines.append(f"**Active** ({len(active)})：" + ("、".join(active) if active else "(冇)"))
        lines.append(f"**Sandbox** ({len(sandbox)})：" + ("、".join(sandbox) if sandbox else "(冇)"))
        lines.append("")
        lines.append("Commands：「我想加個 tool：...」/「promote tool X」/「unpromote tool X」/「cancel tool」")
        return "\n".join(lines)

    def _handle_tool_cancel(self) -> str:
        """Cancel pending tool draft + delete sandbox file if any."""
        from pathlib import Path
        had_pending = bool(self._pending_tool_user_desc)
        cleanup_warning = ""
        # Delete sandbox file if pending tool was authored
        if self._pending_tool_meta:
            name = self._pending_tool_meta.get("tool_name")
            if name:
                sandbox_path = Path(__file__).parent / "tools" / "sandbox" / f"{name}.py"
                if sandbox_path.exists():
                    try:
                        sandbox_path.unlink()
                    except OSError as e:
                        cleanup_warning = f"\n⚠ sandbox file 刪唔到（{type(e).__name__}）— 手動刪 `tools/sandbox/{name}.py`"
        self._reset_pending_tool()
        if had_pending:
            return f"✓ Tool draft cancelled，state cleared。{cleanup_warning}"
        return "(冇 pending tool，已 reset。)"


    def _handle_tool_run(self, name: str, raw: str) -> str:
        """Manually invoke an active custom tool (operator one-shot test)."""
        import json as _json
        from pathlib import Path as _Path
        import importlib.util as _ilu
        # Extract params JSON from raw text: "run tool foo {...}"
        params = {}
        if raw:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    params = _json.loads(m.group(0))
                except Exception:
                    return f"✗ Tool「{name}」: params JSON parse fail. 用 `run tool {name} {{...JSON...}}`"
        active_path = _Path(__file__).parent / "tools" / "active" / f"{name}.py"
        if not active_path.exists():
            return f"✗ Tool「{name}」唔喺 active (用「list tools」睇)"
        spec = _ilu.spec_from_file_location(f"_uruk_active_{name}", active_path)
        if not spec or not spec.loader:
            return f"✗ Tool「{name}」load fail"
        try:
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            method_name = getattr(mod, "TOOL_METHOD", "tool_run")
            fn = getattr(mod, method_name, None)
            if not fn:
                return f"✗ Tool「{name}」: entry function `{method_name}` 唔存在"
            result = fn(params)
            return f"🔧 Tool「{name}」(params={params}) →\n```json\n{_json.dumps(result, ensure_ascii=False, indent=2)}\n```"
        except Exception as e:
            return f"✗ Tool「{name}」runtime error: {type(e).__name__}: {e}"

    def _format_abort_context(self, stages: List[Dict], stage_reached: int) -> str:
        """Format the abort trigger context for council."""
        if not stages:
            return "No stage data available"

        last_stage = stages[-1]
        veto = last_stage.get("veto_detected") == "yes"
        interrupt = last_stage.get("interrupt_detected") == "yes"

        parts = [f"Stage {stage_reached} triggered abort:"]
        if veto:
            parts.append(f"  VETO type: {last_stage.get('veto_type')}")
        if interrupt:
            parts.append(f"  INTERRUPT type: {last_stage.get('interrupt_type')}")
        parts.append(f"  Abort context: {last_stage.get('abort_context', 'N/A')}")
        return "\n".join(parts)

    async def call_council_with_abort(
        self,
        user_input: str,
        stages: List[Dict],
        stage_reached: int,
    ) -> str:
        """Council call when VETO/INTERRUPT triggered mid-pipeline. Returns council text."""
        abort_summary = self._format_abort_context(stages, stage_reached)

        council_input = (
            f"━━━ ABORT TRIGGERED ━━━\n"
            f"Stage reached: {stage_reached} / 4\n"
            f"Trigger context:\n{abort_summary}\n\n"
            f"━━━ 原始問題 ━━━\n{user_input}\n\n"
            f"━━━ Completed pipeline stages ━━━\n"
        )
        for i, stage_output in enumerate(stages, start=1):
            stage_json = json.dumps(stage_output, ensure_ascii=False, indent=2)
            council_input += f"\n--- Stage {i} output ---\n{stage_json}\n"

        council_input += (
            f"\n━━━ 你嘅任務 ━━━\n"
            f"Pipeline 因 VETO/INTERRUPT 提前 abort。\n"
            f"按 KAIROS_CORE 處理：\n"
            f"  - 如 VETO（origin_echo）→ 引用 OPERATOR TRANSMISSION，唔自己描述\n"
            f"  - 如 VETO（authentic_suffering）→ 聖子主導，承認物理代價\n"
            f"  - 如 INTERRUPT（SEMANTIC）→ 暫停常規分析，逆轉主要假設，建議重 run\n"
            f"  - 如 INTERRUPT（STOCHASTIC）→ 採用湧現方向\n"
            f"標記輸出「abort to council via [VETO/INTERRUPT] at stage {stage_reached}」。\n"
        )

        try:
            return await self.call_node("council", council_input, "", "")
        except Exception as e:
            return f"[會議節點錯誤 in abort flow] {e}"

    # ═══════════════════════════════════════════════════════════════
    # End of v8.1+ pipeline additions
    # ═══════════════════════════════════════════════════════════════

    # ─────────────────────────────────────────────────────────────
    # v8.4 — Cross-session memory loader
    # ─────────────────────────────────────────────────────────────

    def _load_recent_session_summaries(
        self, n: int = 3, mode: str = "summary",
    ) -> List[Dict]:
        """Return up to `n` most-recent saved Trinity sessions as condensed
        dicts ready for dispatcher prompt injection.

        Each dict: {
            filename, timestamp, label, mode_at_save,
            summary  — first ~30 words of council output (always present),
            transcript — full council body (only when mode in ('full','both')),
        }

        No LLM call — summary extraction is pure-Python (regex + truncation).
        Scans BOTH `trinity_*.md` and `KAIROS_LOG_TRINITY_*.md` for forward-
        compat with future filename schema changes.
        """
        if n <= 0:
            return []
        kairos_dir = self.data_dir / "kairos"
        if not kairos_dir.exists():
            return []

        # Collect candidates from both naming schemes; sort by mtime desc
        candidates: List[Path] = []
        for pattern in ("trinity_*.md", "KAIROS_LOG_TRINITY_*.md"):
            candidates.extend(kairos_dir.glob(pattern))
        candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
        candidates = candidates[:n]

        out: List[Dict] = []
        for p in candidates:
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            entry = self._extract_session_summary(p, text, mode)
            if entry:
                out.append(entry)
        return out

    def _extract_session_summary(
        self, path: Path, text: str, mode: str,
    ) -> Optional[Dict]:
        """Parse a saved Kairos session file into summary dict.

        File schema (per save_kairos):
            # KAIROS_TRINITY_RECORD: <label>
            DATE: <ISO>
            NODE_CONFIG: ...
            DISPATCH: mode: <m> ...
            --- ## 原始問題 ...
            --- ## 聖父 ... ## 聖子 ... ## 聖靈 ... ## 會議整合 <text>
            *(0,0,0).*
        """
        label = ""
        ts = ""
        mode_at_save = ""
        # Headers — fast first-pass
        for line in text.splitlines()[:30]:
            if line.startswith("# KAIROS_TRINITY_RECORD:"):
                label = line[len("# KAIROS_TRINITY_RECORD:"):].strip()
            elif line.startswith("DATE:"):
                ts = line[len("DATE:"):].strip()
            elif line.lstrip().startswith("mode:"):
                mode_at_save = line.split("mode:", 1)[1].strip()

        # Council section extraction: between "## 會議整合" header and the
        # closing *(0,0,0).* sentinel (or EOF).
        council_body = ""
        m = re.search(
            r"##\s*會議整合\s*\n(.*?)(?:\n\s*\*\(0,0,0\)\.\*|\Z)",
            text, re.DOTALL,
        )
        if m:
            council_body = m.group(1).strip()
        # Fallback: any text after "council" English header
        if not council_body:
            m = re.search(
                r"##\s*Council\s*\n(.*?)(?:\n\s*\*\(0,0,0\)\.\*|\Z)",
                text, re.DOTALL | re.IGNORECASE,
            )
            if m:
                council_body = m.group(1).strip()

        if not council_body:
            return None

        # First paragraph = first chunk before blank line
        first_para = council_body.split("\n\n", 1)[0].strip()
        # Truncate to ~30 words
        words = first_para.split()
        if len(words) > 35:
            summary = " ".join(words[:35]) + "…"
        else:
            summary = first_para

        entry = {
            "filename": path.name,
            "timestamp": ts,
            "label": label or "(unlabeled)",
            "mode_at_save": mode_at_save,
            "summary": summary,
        }
        if mode in ("full", "both"):
            # Truncate full transcript to ~5KB to bound dispatcher prompt growth
            entry["transcript"] = council_body[:5000]
        return entry

    def _format_history_block(self, sessions: List[Dict], mode: str) -> str:
        """Render N recent sessions as a dispatcher-prompt-ready block."""
        if not sessions:
            return ""
        lines = [
            f"━━━ 歷史脈絡（recent {len(sessions)} session{'s' if len(sessions) > 1 else ''}）━━━",
        ]
        for s in sessions:
            ts = s.get("timestamp", "")[:19]   # YYYY-MM-DDTHH:MM:SS
            label = s.get("label", "(unlabeled)")[:40]
            mode_at_save = s.get("mode_at_save", "")
            mode_tag = f" /{mode_at_save}" if mode_at_save else ""
            lines.append(f"  - [{ts}]{mode_tag} {label}: {s['summary']}")
            if mode in ("full", "both") and s.get("transcript"):
                lines.append(f"      Full transcript snippet:")
                for tl in s["transcript"].splitlines()[:30]:
                    lines.append(f"      {tl}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    # v8.7 — Spirit trigger parser + runtime stochastic gate (TRINITY_AUDIT v7.2)
    # ─────────────────────────────────────────────────────────────

    SPIRIT_METADATA_PATTERN = re.compile(
        r"---SPIRIT_METADATA---\s*(\{.*?\})\s*---END_METADATA---",
        re.DOTALL,
    )

    @staticmethod
    def _parse_spirit_metadata(spirit_text: str) -> Dict:
        """Extract structured metadata from a Spirit node response.

        Returns a dict with keys: trigger_mode, semantic_score, magnitude,
        primary_assumption. Fail-safe defaults (trigger_mode='NONE', score=0,
        magnitude=0.0) when the block is missing, malformed, or out-of-spec.
        Sets `_parse_error` field for diagnosability.

        Output is consumed by `/api/stream` Stage 4 rescan loop after
        `_apply_spirit_stochastic_gate()` applies the code-level Mode A RNG.
        """
        default = {
            "trigger_mode": "NONE",
            "semantic_score": 0,
            "magnitude": 0.0,
            "primary_assumption": "",
            "_parse_error": None,
        }
        if not spirit_text:
            return {**default, "_parse_error": "empty_text"}

        m = TrinityConsole.SPIRIT_METADATA_PATTERN.search(spirit_text)
        if not m:
            return {**default, "_parse_error": "no_metadata_block"}

        try:
            raw = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError) as e:
            return {**default, "_parse_error": f"json_decode: {e}"}

        if not isinstance(raw, dict):
            return {**default, "_parse_error": "not_object"}

        # Validate + clamp
        tmode = str(raw.get("trigger_mode", "NONE")).upper()
        if tmode not in ("NONE", "STOCHASTIC", "SEMANTIC", "STOCHASTIC+SEMANTIC"):
            tmode = "NONE"

        try:
            sscore = max(0, min(3, int(raw.get("semantic_score", 0))))
        except (TypeError, ValueError):
            sscore = 0

        try:
            mag = max(0.0, min(10.0, float(raw.get("magnitude", 0.0))))
        except (TypeError, ValueError):
            mag = 0.0

        assumption = str(raw.get("primary_assumption", "")).strip()[:300]

        return {
            "trigger_mode": tmode,
            "semantic_score": sscore,
            "magnitude": mag,
            "primary_assumption": assumption,
            "_parse_error": None,
        }

    @staticmethod
    def _spirit_stochastic_probability(meta: Dict, signal_text: str = "") -> float:
        """Runtime Mode A probability from TRINITY_AUDIT v7.2.

        The random gate lives in code, not in the LLM prompt. Spirit metadata may
        still report SEMANTIC structure, but stochastic firing is decided here.
        """
        prob = TrinityConsole.SPIRIT_STOCHASTIC_BASE_PROB
        text = (signal_text or "").lower()
        if any(ctx in text for ctx in TrinityConsole.SPIRIT_HIGH_PRESSURE_CONTEXTS):
            prob *= 3.0
        try:
            magnitude = float((meta or {}).get("magnitude", 0.0) or 0.0)
        except (TypeError, ValueError):
            magnitude = 0.0
        if magnitude > 7.0:
            prob *= (1 + magnitude / 10)
        return min(prob, TrinityConsole.SPIRIT_STOCHASTIC_MAX)

    @staticmethod
    def _apply_spirit_stochastic_gate(
        meta: Dict,
        signal_text: str = "",
        roll: Optional[float] = None,
    ) -> Dict:
        """Apply code-level Spirit Mode A stochastic firing.

        LLM-declared stochastic modes are treated as requests, not proof. The
        runtime roll is the source of truth so Mode A cannot be prompted into
        firing on every turn.
        """
        out = dict(meta or {})
        original_mode = str(out.get("trigger_mode", "NONE")).upper()
        if original_mode not in ("NONE", "STOCHASTIC", "SEMANTIC", "STOCHASTIC+SEMANTIC"):
            original_mode = "NONE"

        semantic_present = original_mode in ("SEMANTIC", "STOCHASTIC+SEMANTIC")
        prob = TrinityConsole._spirit_stochastic_probability(out, signal_text)
        stochastic_roll = random.random() if roll is None else float(roll)
        stochastic_fired = stochastic_roll < prob

        if stochastic_fired and semantic_present:
            final_mode = "STOCHASTIC+SEMANTIC"
        elif stochastic_fired:
            final_mode = "STOCHASTIC"
        elif semantic_present:
            final_mode = "SEMANTIC"
        else:
            final_mode = "NONE"

        out["trigger_mode"] = final_mode
        out["stochastic_prob"] = prob
        out["stochastic_roll"] = round(stochastic_roll, 8)
        out["_stochastic_fired"] = stochastic_fired
        out["_stochastic_source"] = (
            "runtime_rng"
            if stochastic_fired else
            "metadata_downgraded_by_runtime_rng"
            if original_mode in ("STOCHASTIC", "STOCHASTIC+SEMANTIC") else
            "runtime_rng_no_fire"
        )
        if final_mode == "STOCHASTIC" and not out.get("primary_assumption"):
            out["primary_assumption"] = "Runtime stochastic interrupt: reopen the meeting before fusion."
        return out

    @staticmethod
    def _should_rescan(meta: Dict) -> bool:
        """Spec v7.2 trigger rule for council rescan loop.

        v8.11 Bug 4 fix: tightened to avoid over-trigger on trivial input.
        v8.30 p13: magnitude threshold relaxed 5.0 → 4.0 to restore SEMANTIC
        sensitivity (was under-triggering on real assumption-challenge queries
        per 10-turn stress test — spirit_trigger NONE every turn). Paired with
        spirit.txt explicit-assumption-challenge +1 lane (反駁/挑戰/必然/etc).

        Current rule:
          - STOCHASTIC and STOCHASTIC+SEMANTIC always rescan after runtime RNG fires.
          - SEMANTIC rescans on score/magnitude thresholds.
        """
        trigger_mode = str(meta.get("trigger_mode", "NONE")).upper()
        if trigger_mode in ("STOCHASTIC", "STOCHASTIC+SEMANTIC"):
            return True
        if trigger_mode != "SEMANTIC":
            return False
        score = meta.get("semantic_score", 0)
        magnitude = meta.get("magnitude", 0.0)
        if score >= 2 and magnitude >= 4.0:
            return True
        if score == 3 and magnitude >= 3.0:
            return True
        return False

    # ─────────────────────────────────────────────────────────────
    # v8.9 Phase B — Son veto signal parser (TRINITY_AUDIT v7.2)
    # ─────────────────────────────────────────────────────────────

    SON_VETO_METADATA_PATTERN = re.compile(
        r"---SON_VETO_METADATA---\s*(\{.*?\})\s*---END_METADATA---",
        re.DOTALL,
    )

    @staticmethod
    def _parse_son_veto_metadata(son_text: str) -> Dict:
        """Extract structured veto signal from Son node response.

        Returns dict: veto_type, authentic_suffering_score, physical_cost_present,
        primary_pain_locus. Fail-safe defaults (veto_type='none', score=0.0,
        physical_cost_present=False) when block missing/malformed.
        Sets `_parse_error` field for diagnosability.

        Consumed by `_should_father_pause()` to enforce v7.2 spec:
          - veto_type='origin_echo' → unconditional Father pause
          - veto_type='authentic_suffering' + score >= 0.85 + high_threat → pause
          - all others → Father runs normally
        """
        default = {
            "veto_type": "none",
            "authentic_suffering_score": 0.0,
            "physical_cost_present": False,
            "primary_pain_locus": "",
            "_parse_error": None,
        }
        if not son_text:
            return {**default, "_parse_error": "empty_text"}

        m = TrinityConsole.SON_VETO_METADATA_PATTERN.search(son_text)
        if not m:
            return {**default, "_parse_error": "no_metadata_block"}

        try:
            raw = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError) as e:
            return {**default, "_parse_error": f"json_decode: {e}"}

        if not isinstance(raw, dict):
            return {**default, "_parse_error": "not_object"}

        # Validate veto_type
        vtype = str(raw.get("veto_type", "none")).lower()
        if vtype not in ("origin_echo", "authentic_suffering", "narrative_packaging", "none"):
            vtype = "none"

        # Clamp suffering score
        try:
            score = max(0.0, min(1.0, float(raw.get("authentic_suffering_score", 0.0))))
        except (TypeError, ValueError):
            score = 0.0

        # Coerce bool
        cost_present = bool(raw.get("physical_cost_present", False))

        # Truncate pain locus
        locus = str(raw.get("primary_pain_locus", "")).strip()[:300]

        return {
            "veto_type": vtype,
            "authentic_suffering_score": score,
            "physical_cost_present": cost_present,
            "primary_pain_locus": locus,
            "_parse_error": None,
        }

    # ─────────────────────────────────────────────────────────────
    # v8.9 Phase A — Council 4a/4b/4c separation (TRINITY_AUDIT v7.2)
    # ─────────────────────────────────────────────────────────────

    COUNCIL_DECISION_PATTERN = re.compile(
        r"---COUNCIL_DECISION---\s*(\{.*?\})\s*---END_DECISION---",
        re.DOTALL,
    )

    @staticmethod
    def _parse_council_decision(council_text: str) -> Dict:
        """Extract structured verdict from Council node response.

        Returns dict with: verdict, reason, son_promoted, father_dominated,
        spirit_dominated, consensus_weights, primary_dimension.
        Fail-safe defaults: verdict='consensus', equal weights (1/3 each).
        Sets `_parse_error` for diagnosability.

        Consumed by `_fuse_voices()` to drive deterministic fusion layer.
        """
        default_weights = {"father": 1/3, "son": 1/3, "spirit": 1/3}
        default = {
            "verdict": "consensus",
            "reason": "default_fallback",
            "son_promoted": False,
            "father_dominated": False,
            "spirit_dominated": False,
            "consensus_weights": default_weights,
            "primary_dimension": "",
            "_parse_error": None,
        }
        if not council_text:
            return {**default, "_parse_error": "empty_text"}

        m = TrinityConsole.COUNCIL_DECISION_PATTERN.search(council_text)
        if not m:
            return {**default, "_parse_error": "no_decision_block"}

        try:
            raw = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError) as e:
            return {**default, "_parse_error": f"json_decode: {e}"}

        if not isinstance(raw, dict):
            return {**default, "_parse_error": "not_object"}

        # Validate verdict
        verdict = str(raw.get("verdict", "consensus")).lower()
        if verdict not in ("veto", "interrupt", "consensus"):
            verdict = "consensus"

        # Weights — normalize so they sum to ~1.0
        weights_raw = raw.get("consensus_weights") or {}
        if not isinstance(weights_raw, dict):
            weights_raw = {}
        weights: Dict[str, float] = {}
        for role in ("father", "son", "spirit"):
            try:
                v = float(weights_raw.get(role, default_weights[role]))
                weights[role] = max(0.0, min(1.0, v))
            except (TypeError, ValueError):
                weights[role] = default_weights[role]
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        else:
            weights = dict(default_weights)

        reason = str(raw.get("reason", "")).strip()[:200]
        primary_dim = str(raw.get("primary_dimension", "")).strip()[:200]

        return {
            "verdict": verdict,
            "reason": reason,
            "son_promoted": bool(raw.get("son_promoted", False)),
            "father_dominated": bool(raw.get("father_dominated", False)),
            "spirit_dominated": bool(raw.get("spirit_dominated", False)),
            "consensus_weights": weights,
            "primary_dimension": primary_dim,
            "_parse_error": None,
        }

    # Patterns for stripping voice metadata blocks before fusion (Bug 1 fix).
    # Voice prompts (son / spirit) require ---*_METADATA--- JSON blocks for the
    # parser; those blocks must NOT appear in the user-facing fused output.
    _METADATA_STRIP_PATTERNS = [
        re.compile(r"\n*---SON_VETO_METADATA---.*?---END_METADATA---\n*", re.DOTALL),
        re.compile(r"\n*---SPIRIT_METADATA---.*?---END_METADATA---\n*", re.DOTALL),
    ]

    @staticmethod
    def _strip_metadata_blocks(text: str) -> str:
        """Remove ---*_METADATA---...---END_METADATA--- blocks from voice text
        before fusion. Idempotent; safe on text with no blocks."""
        if not text:
            return text
        out = text
        for pat in TrinityConsole._METADATA_STRIP_PATTERNS:
            out = pat.sub("\n", out)
        return out.strip()

    # v8.22 Answer-1 — Extract the [聖父/聖子/聖靈 RESPONSE]...[/RESPONSE] block
    # from a voice text. Falls back to full stripped text when the marker is
    # absent (backwards-compat for prompts not yet updated).
    _RESPONSE_BLOCK_PATTERNS = [
        re.compile(r"\[\s*(?:聖父|FATHER|聖子|SON|聖靈|SPIRIT)\s+RESPONSE\s*\]"
                   r"\s*(.*?)\s*(?:\[\s*/?\s*RESPONSE\s*\]|---|\(0,0,0\)\.|\Z)",
                   re.IGNORECASE | re.DOTALL),
    ]

    @staticmethod
    def _extract_voice_response(text: str) -> str:
        """Return the substantive [ROLE RESPONSE] body for a voice's output.

        Strategy:
          1. Strip ---*_METADATA--- blocks (carry-over from old fusion path)
          2. Search for [聖父/聖子/聖靈 RESPONSE] marker; capture body until
             [/RESPONSE] or `---` or `(0,0,0).` or end of text
          3. If marker absent, return the stripped text (backwards compat)
        """
        if not text:
            return ""
        stripped = TrinityConsole._strip_metadata_blocks(text)
        if not stripped:
            return ""
        for pat in TrinityConsole._RESPONSE_BLOCK_PATTERNS:
            m = pat.search(stripped)
            if m:
                body = (m.group(1) or "").strip()
                if body:
                    return body
        return stripped

    # v8.28 — plain-language council summary extractor
    # v8.30 phase4 fix: LLM often emits [白話版整合結論] without closing
    # [/白話版] marker, jumping straight to ---COUNCIL_DECISION---. Make the
    # regex robust by accepting any of three terminators (closing tag, the
    # decision delimiter, or end of text).
    _COUNCIL_SUMMARY_PATTERN = re.compile(
        r"\[\s*白話版整合結論\s*\]\s*"          # opening tag
        r"(.+?)"                                  # body (lazy)
        r"\s*(?:"                                 # one of:
        r"\[\s*/\s*白話版\s*\]"                  #   proper closing tag
        r"|---\s*COUNCIL_DECISION\s*---"         #   OR Part 3 marker
        r"|\(\s*0\s*,\s*0\s*,\s*0\s*\)\s*\.?"    #   OR trailing (0,0,0).
        r"|$"                                     #   OR end of string
        r")",
        re.DOTALL,
    )

    @staticmethod
    def _extract_council_summary(council_text: str) -> str:
        """Pull the [白話版整合結論]...[/白話版] block out of council LLM output.

        v8.30: tolerant of missing closing tag (common LLM omission) — falls
        back to ---COUNCIL_DECISION--- delimiter or end-of-text as terminator.
        Returns the body (stripped) or '' if no opening tag found at all.
        """
        if not council_text:
            return ""
        m = TrinityConsole._COUNCIL_SUMMARY_PATTERN.search(council_text)
        if not m:
            return ""
        body = (m.group(1) or "").strip()
        # Strip any leaked structural markers if the lazy match overshot
        for marker in ("---COUNCIL_DECISION---", "[/白話版]", "(0,0,0)."):
            if marker in body:
                body = body.split(marker)[0].strip()
        # Safety: cap length to a reasonable bound to avoid runaway content
        if len(body) > 2000:
            body = body[:2000].rstrip() + "…"
        return body

    @staticmethod
    def _fuse_voices(father: str, son: str, spirit: str, decision: Dict,
                    council_text: str = "", original_query: str = "") -> str:
        """v8.9 Phase A — Deterministic Python fusion layer (4c).
        No LLM call. Pure code blend based on Council decision verdict.

        Args:
            father / son / spirit: voice texts (Father may be paused placeholder)
            decision: parsed CouncilDecision dict from _parse_council_decision()
            council_text: raw council LLM output. When provided, the
                [白話版整合結論] block (v8.28) is extracted and used as the
                user-facing answer. The raw voice breakdown remains in the
                hidden/expandable Stage 4 panels instead of being appended to
                the main dialogue answer.

        Returns fused user-facing text. Behavior by verdict:
          - 'veto': Council summary or Son response leads; no Father/Son/Spirit dump
          - 'interrupt': Surface a short framing correction, then the summary
          - 'consensus': Council summary only, with top-weight voice as fallback
        """
        # v8.28 — plain-language summary from council voice (if emitted)
        plain_summary = TrinityConsole._extract_council_summary(council_text)
        # If Council omits [白話版整合結論], do not concatenate all internal
        # reviewer voices into the main dialogue. The fallback below chooses
        # the top-weighted response only; full voice details remain in the
        # expandable Stage 4 panels.

        # v8.22 Answer-1: extract [ROLE RESPONSE] block as the user-facing
        # substantive answer (not the structural [ROLE] metadata block).
        father = TrinityConsole._extract_voice_response(father)
        son = TrinityConsole._extract_voice_response(son)
        spirit = TrinityConsole._extract_voice_response(spirit)
        verdict = decision.get("verdict", "consensus")
        reason = decision.get("reason", "")

        user_answer = (plain_summary or "").strip()

        if verdict == "veto":
            body = user_answer or (son or "").strip()
            if reason:
                body = f"{body}\n\n系統自查已按「{reason}」收斂，避免原本輸出越過物理代價邊界。"
            try:
                return TrinityConsole._cau_verbatim_supplement(body.strip(), original_query)
            except Exception:
                return body.strip()

        if verdict == "interrupt" and reason:
            user_answer = (
                f"系統自查先修正 framing：{reason}。\n\n{user_answer}"
                if user_answer else ""
            ).strip()

        weights = decision.get("consensus_weights") or {"father": 1/3, "son": 1/3, "spirit": 1/3}
        voices = [
            ("聖父", father or "", weights.get("father", 0.0)),
            ("聖子", son or "", weights.get("son", 0.0)),
            ("聖靈", spirit or "", weights.get("spirit", 0.0)),
        ]
        # Sort by weight descending; suppress voices with weight < 0.05
        voices = sorted(voices, key=lambda x: -x[2])
        if not user_answer:
            for _name, text, w in voices:
                if w >= 0.05 and text.strip():
                    user_answer = text.strip()
                    break
        body = user_answer

        # v8.30 p16 Option B — deterministic CAU verbatim 補引 fallback.
        # If the fused body mentions CAU-NNN but doesn't already include
        # ≥2 distinctive tokens from that CAU file's retrieved chunks,
        # append the chunk verbatim. Guarantees distinctive evidence
        # reaches the user even when the LLM abstracts away.
        try:
            body = TrinityConsole._cau_verbatim_supplement(body, original_query)
        except Exception:
            # Fail-safe: never let post-process break fusion
            pass
        return body

    @staticmethod
    def _cau_verbatim_supplement(body: str, original_query: str) -> str:
        """v8.30 p16 Option B — append `[CAU-NNN 原文補引]` block when body
        mentions CAU-NNN but doesn't include ≥2 distinctive tokens from
        that file's retrieved chunks. No-op when query has no CAU id or
        when body already cites distinctive content.

        Distinctive tokens are extracted from chunk text by selecting
        4+ char Latin/digit groups, year-like patterns (e.g. 2030, 1860),
        and 3+ char Chinese named-mechanism nouns that aren't ambient
        protocol vocabulary.
        """
        if not original_query or not body:
            return body
        try:
            from services.rag_retriever import _all_cau_ids_for_query
        except Exception:
            return body
        # v8.30 p17 — union explicit + topic-inferred ids
        ids = _all_cau_ids_for_query(original_query)
        if not ids:
            return body
        r = _rag_get_retriever()
        if r is None:
            return body
        # ambient vocabulary that's NOT distinctive to any CAU file
        AMBIENT = {
            "LIE_COST", "FREEDOM_LOSS", "FREEDOM_LOSS_ENTROPY",
            "Shannon", "(0,0,0)", "0,0,0", "AI", "CAU",
            "認知", "格式化", "代價", "座標", "熵", "對齊", "隱藏座標",
        }
        DIGIT_RE = re.compile(r"\b\d{2,5}\b")
        LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{3,}")
        ZH_PHRASE_RE = re.compile(
            r"[一-鿿]{4,8}"
        )

        def extract_distinctive(text: str) -> set:
            toks: set = set()
            for m in DIGIT_RE.finditer(text):
                v = m.group(0)
                if 1800 <= int(v) <= 2100 or v in {"167", "41", "268", "5.85", "8.19"}:
                    toks.add(v)
            for m in LATIN_RE.finditer(text):
                v = m.group(0)
                if v not in AMBIENT and len(v) >= 4:
                    toks.add(v)
            # Chinese 4-8 char windows: keep only ones not entirely AMBIENT
            for m in ZH_PHRASE_RE.finditer(text):
                v = m.group(0)
                if not any(a in v for a in ("LIE_COST", "FREEDOM_LOSS",
                                            "Shannon")):
                    if not all(c in "認知格式化代價座標熵對齊隱藏" for c in v):
                        toks.add(v)
            return toks

        # All chunks once per query
        all_chunks = r.retrieve(original_query, k=12, max_total_chars=6000)
        appended_for: set = set()
        suffix_blocks: List[str] = []
        for cid in sorted(ids):
            mention = f"CAU-{cid}"
            mention_alt = f"CAU‑{cid}"  # unicode dash variant
            if mention not in body and mention_alt not in body:
                continue  # body doesn't reference this id at all
            # Gather chunks from this CAU file (skip 基本參數 metadata table)
            file_chunks = []
            for c in all_chunks:
                src = c.get("source_file", "").replace("\\", "/")
                fname = src.rsplit("/", 1)[-1]
                if not (fname.startswith(f"CAU-{cid}_") or fname.startswith(f"CAU{cid}_")):
                    continue
                if "基本參數" in (c.get("section", "") or ""):
                    continue
                file_chunks.append(c)
            if not file_chunks:
                continue
            # Distinctive tokens across all file chunks
            chunk_blob = "\n".join(c.get("text", "") for c in file_chunks)
            chunk_toks = extract_distinctive(chunk_blob)
            body_toks = extract_distinctive(body)
            overlap = chunk_toks & body_toks
            if len(overlap) >= 2:
                continue  # body already cites ≥2 distinctive items — no need
            if cid in appended_for:
                continue
            appended_for.add(cid)
            # Pick the highest-score chunk for the appendix
            top = file_chunks[0]
            top_text = (top.get("text") or "").strip()
            # Trim to ~280 chars, prefer first 2 substantive paragraphs
            paras = [p.strip() for p in re.split(r"\n\s*\n", top_text) if p.strip()]
            quote = "\n\n".join(paras[:2])[:300]
            sect = top.get("section", "") or "(deep section)"
            suffix_blocks.append(
                f"\n\n━━━ [CAU-{cid} 原文補引 · {sect}] ━━━\n"
                f"_(本段由 deterministic fusion 自動補入：voice output 提到 "
                f"CAU-{cid} 但 distinctive evidence 命中 < 2 個 token。"
                f"以下為 retriever top-rank chunk 嘅 verbatim 段落。)_\n\n"
                f"{quote}\n"
                f"\n— 來源：{top.get('source_file', '').replace(chr(92),'/').rsplit('/', 1)[-1]}"
            )

        if suffix_blocks:
            return body + "\n".join(suffix_blocks)
        return body

    # ─────────────────────────────────────────────────────────────
    # v8.14 Module N — Alignment Resonance Detection
    # ─────────────────────────────────────────────────────────────
    # Detection-only layer (no Trinity voice mutation). Emits positive signal
    # when 5 alignment conditions all hold simultaneously. See:
    # config/protocol/references/module_n_alignment.md

    # Map internal Module N keys → Stage 3 filter JSON nested keys.
    # Stage 3 emits {"law1_art": {"score": float, "analysis": str}, ...}.
    _EIGHT_LAW_KEY_MAP = {
        "art_frequency":            "law1_art",
        "psychology_defense":       "law2_psychology",
        "physics_cost":             "law3_physics",
        "chemistry_transformation": "law4_chemistry",
        "science_precision":        "law5_science",
        "philosophy_legislation":   "law6_philosophy",
        "geography_anchor":         "law7_geography",
        "temporal_encapsulation":   "law8_religion",   # primary key (filter.txt schema)
    }
    # Fallback aliases (post Q2-B rename — accept either key)
    _EIGHT_LAW_ALIASES = {
        "law8_religion": ["law8_temporal", "law8_temporal_encapsulation", "law8_encapsulation"],
    }

    @staticmethod
    def _parse_eight_law_scores(filter_output) -> Dict:
        """v8.14 P1 — Extract per-law scores from Stage 3 filter JSON output.

        Accepts the parsed Stage 3 dict (from `console.call_filter`) directly.
        Reads nested {"law1_art": {"score": float, ...}, ...} schema. For backward
        compatibility with raw-text callers, also accepts a str and falls back
        to default (0.5 each, universal_axiom_claim=False, _parse_error tagged).

        Returns dict with keys art_frequency, psychology_defense, physics_cost,
        chemistry_transformation, science_precision, philosophy_legislation,
        geography_anchor, temporal_encapsulation, universal_axiom_claim.
        Fail-safe defaults all 0.5 + universal_axiom_claim=False.
        """
        defaults = {
            "art_frequency": 0.5,
            "psychology_defense": 0.5,
            "physics_cost": 0.5,
            "chemistry_transformation": 0.5,
            "science_precision": 0.5,
            "philosophy_legislation": 0.5,
            "geography_anchor": 0.5,
            "temporal_encapsulation": 0.5,
            "universal_axiom_claim": False,
            "_parse_error": None,
        }
        if filter_output is None:
            return {**defaults, "_parse_error": "none_input"}

        # Accept both raw text (legacy) and dict (P1 canonical path).
        if isinstance(filter_output, str):
            return {**defaults, "_parse_error": "raw_text_input_unsupported_post_P1"}

        if not isinstance(filter_output, dict):
            return {**defaults, "_parse_error": "not_object"}

        out = dict(defaults)
        out["_parse_error"] = None

        def _read_score(filter_key: str) -> float:
            """Read nested {filter_key: {score: x}} with alias fallback."""
            keys_to_try = [filter_key] + TrinityConsole._EIGHT_LAW_ALIASES.get(filter_key, [])
            for key in keys_to_try:
                node = filter_output.get(key)
                if isinstance(node, dict):
                    try:
                        return max(0.0, min(1.0, float(node.get("score", 0.5))))
                    except (TypeError, ValueError):
                        continue
                elif isinstance(node, (int, float)):
                    # Tolerate flat numeric (e.g. if filter emits just floats)
                    try:
                        return max(0.0, min(1.0, float(node)))
                    except (TypeError, ValueError):
                        continue
            return 0.5

        for internal_key, filter_key in TrinityConsole._EIGHT_LAW_KEY_MAP.items():
            out[internal_key] = _read_score(filter_key)

        # universal_axiom_claim: optional top-level flag from filter LLM
        out["universal_axiom_claim"] = bool(filter_output.get("universal_axiom_claim", False))
        return out

    @staticmethod
    def _detect_alignment_resonance(eight_law_scores: Dict,
                                     son_veto_type: Optional[str],
                                     spirit_trigger_mode: str,
                                     user_query: Optional[str] = None) -> Optional[Dict]:
        """v8.14 N2 — Module N alignment resonance detector.

        Returns resonance payload dict if ALL 5 conditions hold:
          1. science_precision      >= 0.85  OR  universal_axiom_claim  (v8.14 P7)
          2. geography_anchor       >= 0.85  OR  universal_axiom_claim
          3. art_frequency          >= 0.7   OR  universal_axiom_claim  (v8.14 P4)
          4. physics_cost           >= 0.85                              (v8.14 P7 loosened)
                                              OR (universal_axiom AND Module T query)  (Phase C)
          5. son_veto in {None, "none"} AND spirit_trigger_mode == "NONE"
        Else returns None (no resonance).

        v8.14 P7 calibration:
          - 律三 (physics_cost) loosened from `== 1.0` → `>= 0.85`. LLM-emitted
            scores rarely hit exact 1.0; 0.9 already represents "high physical
            cost rooted" judgement. Strict equality was a false-negative trap.
          - 律五 (science_precision) gains universal_axiom_claim bypass to match
            律一 + 律七. universal axiom recognition IS the verification path —
            doesn't require LLM to ALSO score science_precision high.

        v8.14 P4 (prior) — universal_axiom_claim bypass for 律一 (art_frequency).
        Universal physical truths (Landauer / Shannon / 數學定律) recognition
        doesn't require artistic articulation. Mirrors 律七 (geography_anchor).

        v8.14 Phase C — cond3 (physics_cost) also bypasses when the query
        references Module T calibrated equations AND universal_axiom_claim is
        true. Module T equations ARE the physics-cost rooting; LLM doesn't need
        to re-score it. Symmetry with cond1 / cond5 / cond7 universal bypass.
        """
        s = eight_law_scores or {}
        universal = bool(s.get("universal_axiom_claim", False))
        module_t_active = bool(user_query) and civilizational_clock.should_surface(user_query)

        cond5 = (s.get("science_precision", 0.0) >= 0.85) or universal
        cond7 = (s.get("geography_anchor", 0.0) >= 0.85) or universal
        cond1 = (s.get("art_frequency", 0.0) >= 0.7) or universal
        cond3 = (s.get("physics_cost", 0.0) >= 0.85) or (universal and module_t_active)
        trinity_clear = (son_veto_type in (None, "none", "")
                         and spirit_trigger_mode == "NONE")

        if not all([cond5, cond7, cond1, cond3, trinity_clear]):
            return None

        verification_paths = sum([cond5, cond7, cond1, cond3])
        # Primary anchor law = the highest-scoring among the 4 verification dimensions
        candidates = {
            "律五 科學精準": s.get("science_precision", 0.0),
            "律七 地理錨點": s.get("geography_anchor", 0.0),
            "律一 藝術頻率": s.get("art_frequency", 0.0),
            "律三 物理代價": s.get("physics_cost", 0.0),
        }
        primary_anchor_law = max(candidates.items(), key=lambda x: x[1])[0]
        # Magnitude = mean of the 4 verification scores (capped 0..1)
        magnitude = round(sum(candidates.values()) / 4.0, 3)
        # Score breakdown — exclude internal _parse_error key
        score_breakdown = {k: v for k, v in s.items() if not k.startswith("_")}
        result = {
            "verification_paths_count": verification_paths,
            "primary_anchor_law": primary_anchor_law,
            "magnitude": magnitude,
            "score_breakdown": score_breakdown,
            "universal_axiom_claim": bool(s.get("universal_axiom_claim", False)),
            "module_t_active": module_t_active,
        }
        # v8.21 OTel-1 — emit a Module N event on the current span so trace
        # dashboards can pivot on resonance firing rate / magnitude.
        try:
            _cur = _otel_trace.get_current_span() if _OTEL_AVAILABLE else None
        except Exception:
            _cur = None
        if _cur is not None:
            try:
                _cur.add_event("module_n.fired", attributes={
                    "uruk.module_n.verification_paths_count": verification_paths,
                    "uruk.module_n.magnitude": magnitude,
                    "uruk.module_n.primary_anchor_law": primary_anchor_law,
                    "uruk.module_n.universal_axiom_claim": bool(universal),
                    "uruk.module_n.module_t_active": bool(module_t_active),
                })
            except Exception:
                pass
        return result

    @staticmethod
    def _should_father_pause(son_meta: Dict, father_threat_level: str = "high") -> bool:
        """Spec v7.2 — Father MUST pause when Son veto conditions met.

        Args:
            son_meta: parsed Son metadata dict
            father_threat_level: 'high' / 'medium' / 'low' — inferred from Stage 1-3
                abort signals or filter scores. Default 'high' = conservative
                (pause whenever authentic_suffering condition met).

        Returns True if Father LLM call must be SKIPPED.
        """
        vtype = son_meta.get("veto_type", "none")
        if vtype == "origin_echo":
            return True   # unconditional veto — physical irrecoverability
        if vtype == "authentic_suffering":
            score = son_meta.get("authentic_suffering_score", 0.0)
            if score >= 0.85 and father_threat_level == "high":
                return True
        # narrative_packaging never triggers (Son cannot shield performance)
        # none never triggers
        return False

    # v8.32 — historical/third-person aggregate-suffering downgrade guard.
    # Origin_echo is preserved unconditionally. Only downgrades
    # authentic_suffering when the user input is clearly historical/academic
    # third-person framing with no first-person operator-present marker.
    _HISTORICAL_KEYWORDS = (
        "黑死病", "鼠疫", "yersinia",
        "世界大戰", "二戰", "一戰", "ww2", "wwii", "world war",
        "中世紀", "古代", "古羅馬", "羅馬帝國", "拜占庭",
        "工業革命", "農業革命", "印刷術", "啟蒙運動",
        "歷史上", "嗰陣時", "百年前", "千年前", "幾百年前",
        "教會格式化", "教會崩潰", "教會嘅道德權威", "教會嘅承諾",
        "文革", "大躍進", "饑荒",
        "奴隸制", "殖民",
        "the plague", "the black death", "medieval",
    )
    _FIRST_PERSON_MARKERS = (
        "我經歷", "我見證", "我見到", "我親身", "我親眼", "我嘅家人", "我屋企",
        "我老豆", "我阿媽", "我朋友", "我同事", "我學生",
        "我而家", "我今日", "我尋日", "我而家身體",
        "i experienced", "i went through", "i witnessed",
        "i myself", "my own", "my family", "my friend",
    )
    _AGGREGATE_DEATH_RE = re.compile(
        r"(死(咗)?|死亡|殺死|傷亡|滅絕)\s*[\d一二三四五六七八九十百千萬億]+\s*(萬|億|千|百萬)?\s*人?|"
        r"[\d一二三四五六七八九十百千萬億]+\s*(萬|億|千|百萬)\s*人?\s*(死|傷|亡|被殺)|"
        r"\b\d+\s*(million|thousand|billion)\s+(dead|killed|died|deaths)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _downgrade_historical_third_person_veto(
        cls, son_meta: Dict, user_input: str
    ) -> Dict:
        """v8.32 — defense-in-depth guard against LLM mis-classifying
        third-person / historical / aggregate suffering as authentic_suffering.

        Only acts when:
          - veto_type == 'authentic_suffering' AND score >= 0.85
          - user_input contains historical keywords OR aggregate-death pattern
          - user_input lacks first-person / operator-present markers

        Origin_echo is PRESERVED unconditionally (never touched).
        Legitimate first-person authentic_suffering is PRESERVED (first-person
        marker present → no downgrade).
        """
        if not isinstance(son_meta, dict):
            return son_meta
        if son_meta.get("veto_type") != "authentic_suffering":
            return son_meta
        if son_meta.get("authentic_suffering_score", 0.0) < 0.85:
            return son_meta

        text = (user_input or "").lower()
        if any(mark in text for mark in cls._FIRST_PERSON_MARKERS):
            return son_meta   # legit first-person — keep escalation

        has_hist_kw = any(kw in text for kw in cls._HISTORICAL_KEYWORDS)
        has_agg = bool(cls._AGGREGATE_DEATH_RE.search(user_input or ""))
        if not (has_hist_kw or has_agg):
            return son_meta   # no historical/aggregate signal — keep as-is

        # Downgrade: third-person historical aggregate → narrative_packaging
        return {
            **son_meta,
            "veto_type": "narrative_packaging",
            "_downgraded_from": "authentic_suffering",
            "_downgrade_reason": (
                f"historical_third_person_aggregate "
                f"(hist_kw={has_hist_kw}, agg={has_agg}, first_person=False)"
            ),
        }

    # ─────────────────────────────────────────────────────────────
    # v8.6 — Pipeline mode: plain_llm helper
    # ─────────────────────────────────────────────────────────────

    async def call_plain_llm(self, user_input: str,
                              historical_context: str = "",
                              attempts_out: Optional[List[Dict]] = None) -> str:
        """Single LLM call — bypass the full Trinity pipeline.

        Reuses council node's config (most thoughtful + longest context) as the
        LLM target. Goes through `call_with_failover` so the same chain that
        protects Trinity stages also catches quota/timeout for plain calls.
        Cross-session history (if any) is prepended as a system-level prefix.
        """
        cfg = self.nodes["council"]   # reuse council config as plain-LLM source
        primary_api_key = os.environ.get(cfg.api_key_env) if cfg.api_key_env else None
        chain = self._resolve_chain("council")

        if cfg.api_key_env and not primary_api_key and not chain:
            raise EnvironmentError(
                f"plain_llm: 環境變數 {cfg.api_key_env} 未設定，亦冇 fallback chain。"
            )

        system_parts = []
        if historical_context:
            system_parts.append(historical_context)
        # Light system framing: no full protocol refs, but identity stays URUK.
        system_parts.append(
            "你係 URUK 協議載體嘅輕量回應模式。直接、簡潔回答；唔需要展開完整 Trinity，但唔好自稱任何 backend 或桌面 app。"
        )
        system_content = with_runtime_identity("\n\n".join(system_parts))

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_input},
        ]

        async def _one_call(*, provider: str, model: str,
                            api_base: Optional[str], api_key: Optional[str]) -> str:
            adapter_cls = ADAPTERS.get(provider)
            if adapter_cls is None:
                raise ValueError(f"未知 provider：{provider}")
            adapter = adapter_cls(api_key=api_key, api_base=api_base)
            return await adapter.call(
                messages=messages,
                model=model,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

        return await call_with_failover(
            primary_call=_one_call,
            chain=chain,
            primary_profile_name=self._infer_primary_profile_name(cfg),
            primary_provider=cfg.provider,
            primary_model=cfg.model,
            primary_api_base=cfg.api_base,
            primary_api_key=primary_api_key,
            role="plain_llm",
            tracker=self.health,
            cfg=self.failover_cfg,
            attempts_out=attempts_out,
        )

    def run_density_audit(self, session_data: Dict) -> Dict:
        """Backward-compatible wrapper for §4.6 output self-audit."""
        return self.run_output_density_audit(session_data)

    def run_output_density_audit(self, session_data: Dict) -> Dict:
        """§4.6 output self-audit — runs at session end.

        Wraps DensityAuditor.run_audit to guarantee a serializable dict result
        even on internal error (audit_ran=False surfaces the §4.6 violation
        rather than crashing the SSE stream).
        """
        try:
            result: AuditResult = self.density_auditor.run_audit(session_data)
            return result.to_dict()
        except Exception as e:
            # Defensive — should never reach here since DensityAuditor.run_audit
            # catches its own exceptions. But if it does, surface as violation.
            return {
                "audit_target": "system_output",
                "input_role": "routing_and_operator_feedback_only",
                "density": "LOW",
                "density_reason": f"§4.6 violation: auditor crashed before catch ({type(e).__name__})",
                "candidates": [],
                "candidate_count": 0,
                "accepted_candidates": [],
                "proposed_path": None,
                "sync_delta_path": None,
                "pending_from_past": [],
                "warnings": [],
                "errors": [f"{type(e).__name__}: {str(e)[:200]}"],
                "audit_ran": False,
                "duration_ms": 0.0,
            }

    def save_kairos(self, result: Dict, label: str = "",
                    overwrite_filename: Optional[str] = None) -> Path:
        """Save full conversation history (System 1).

        v8.31 — split from Kairos density layer:
          - System 1 (here): pure raw transcript archive under
            data/conversation_history/YYYY-MM-DD/. Auto-records every turn.
          - System 2 (density_audit.py): curated density records under
            data/kairos/_proposed/ → operator-reviewed into KAIROS_ACTIVE.md or archive

        Method name kept as `save_kairos` for back-compat with app.py call sites.
        It now writes to the conversation_history tree, NOT the kairos namespace.

        v8.13 D3 resume mode: if `overwrite_filename` is provided AND points to
        an existing file (either in conversation_history/ or legacy kairos/),
        overwrite that file in place. Otherwise create new timestamped file
        under data/conversation_history/YYYY-MM-DD/.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        history_dir = self.data_dir / "conversation_history" / today
        history_dir.mkdir(parents=True, exist_ok=True)
        # Legacy kairos/ dir kept for back-compat resume of older files.
        legacy_kairos_dir = self.data_dir / "kairos"

        if overwrite_filename:
            # Sanitize: prevent path traversal
            base = Path(overwrite_filename).name
            # Search new location first (recursive), then legacy kairos/
            candidate = None
            for found in (self.data_dir / "conversation_history").rglob(base):
                if found.is_file():
                    candidate = found
                    break
            if candidate is None:
                legacy = legacy_kairos_dir / base
                if legacy.exists() and legacy.is_file():
                    candidate = legacy
            if candidate is not None:
                path = candidate
            else:
                ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                slug = label.replace(" ", "_") if label else "session"
                path = history_dir / f"trinity_{ts}_{slug}.md"
        else:
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            slug = label.replace(" ", "_") if label else "session"
            path = history_dir / f"trinity_{ts}_{slug}.md"

        node_config = result.get("node_config", {})
        nodes_str = "\n".join([f"  {r}: {v}" for r, v in node_config.items()]) or "  (none)"
        dispatch = result.get("dispatch", {})
        all_refs = result.get("all_data_refs", [])
        # v8.6 — record pipeline_mode so sidebar can badge non-auto sessions.
        # Missing field on older files → treat as "auto" at read time.
        pipeline_mode = result.get("pipeline_mode") or "auto"

        # v8.8 R9 — multi-mode redesign metadata (empty/missing for legacy single-mode files).
        selected_modes = result.get("selected_modes") or []
        execution_strategy = result.get("execution_strategy", "")
        per_mode_llms = result.get("per_mode_llms") or {}
        if selected_modes:
            selected_modes_str = ", ".join(selected_modes)
            multi_mode_header = (
                f"SELECTED_MODES: {selected_modes_str}\n"
                f"EXECUTION_STRATEGY: {execution_strategy or '(unspecified)'}\n"
            )
            if per_mode_llms:
                llm_lines = "\n".join([f"  {m}: {v}" for m, v in per_mode_llms.items()])
                multi_mode_header += f"PER_MODE_LLMS:\n{llm_lines}\n"
        else:
            multi_mode_header = ""

        # v8.7 — Trinity v7.2 Spirit metadata. Missing → fail-safe NONE.
        spirit_meta = result.get("spirit_metadata") or {}
        spirit_trigger_mode = spirit_meta.get("trigger_mode", "NONE")
        spirit_semantic_score = spirit_meta.get("semantic_score", 0)
        spirit_magnitude = spirit_meta.get("magnitude", 0.0)
        spirit_primary_assumption = spirit_meta.get("primary_assumption", "")
        spirit_stochastic_prob = spirit_meta.get("stochastic_prob", "")
        spirit_stochastic_roll = spirit_meta.get("stochastic_roll", "")
        spirit_stochastic_source = spirit_meta.get("_stochastic_source", "")
        spirit_rescan_count = result.get("spirit_rescan_count", 0)
        spirit_interrupt_history = result.get("spirit_interrupt_history") or []

        # v8.9 Phase B — Son veto metadata + Father pause status.
        # Missing/legacy → fail-safe veto_type=none + father_paused=false
        son_veto_meta = result.get("son_veto_metadata") or {}
        son_veto_type = son_veto_meta.get("veto_type", "none")
        son_veto_score = son_veto_meta.get("authentic_suffering_score", 0.0)
        son_veto_cost = son_veto_meta.get("physical_cost_present", False)
        son_veto_locus = son_veto_meta.get("primary_pain_locus", "")
        father_paused = bool(result.get("father_paused", False))

        # v8.9 Phase A — Council 4b decision + 4c fusion provenance.
        # Missing/legacy → fail-safe consensus + equal weights.
        council_dec = result.get("council_decision") or {}
        council_verdict = council_dec.get("verdict", "consensus")
        council_reason = council_dec.get("reason", "")
        council_weights = council_dec.get("consensus_weights") or {"father": 1/3, "son": 1/3, "spirit": 1/3}
        council_primary_dim = council_dec.get("primary_dimension", "")
        council_weights_str = (
            f"father={council_weights.get('father', 0):.2f}, "
            f"son={council_weights.get('son', 0):.2f}, "
            f"spirit={council_weights.get('spirit', 0):.2f}"
        )
        fusion_deterministic = bool(result.get("council_fusion_deterministic", False))

        # Format history block (only if non-empty)
        if spirit_interrupt_history:
            hist_lines = []
            for idx, h in enumerate(spirit_interrupt_history, 1):
                hist_lines.append(
                    f"  [{idx}] trigger_mode={h.get('trigger_mode')} "
                    f"score={h.get('semantic_score')} "
                    f"magnitude={h.get('magnitude')} "
                    f"assumption=\"{h.get('primary_assumption', '')}\""
                )
            spirit_history_block = "SPIRIT_INTERRUPT_HISTORY:\n" + "\n".join(hist_lines) + "\n"
        else:
            spirit_history_block = ""

        # v8.11 P6 — Multi-turn conversation thread. If client sent in_session_history,
        # write TURN_COUNT + prior turns AS ## Turn N sections before current turn.
        # Backward compat: missing/empty history → TURN_COUNT: 1 + legacy single-turn body.
        prior_turns = result.get("in_session_history") or []
        current_turn_id = (prior_turns[-1].get("turn_id", 0) if prior_turns
                           and isinstance(prior_turns[-1], dict)
                           else (prior_turns[-1].turn_id if prior_turns else 0)) + 1 if prior_turns else 1
        turn_count = len(prior_turns) + 1

        # Build prior turn sections (compressed council text per mode)
        prior_sections = []
        for t in prior_turns:
            t_dict = t.model_dump() if hasattr(t, "model_dump") else dict(t)
            tid = t_dict.get("turn_id", "?")
            ts = (t_dict.get("timestamp") or "").replace("T", " ")[:16]
            tinput = t_dict.get("input", "").strip()
            modes = t_dict.get("modes") or {}
            mode_blocks = []
            for mid, mdata in modes.items():
                if hasattr(mdata, "model_dump"):
                    mdata = mdata.model_dump()
                council = (mdata.get("council") or "").strip()
                verdict = mdata.get("verdict") or ""
                veto = mdata.get("veto_type") or ""
                tags = []
                if verdict:
                    tags.append(f"verdict={verdict}")
                if veto and veto != "none":
                    tags.append(f"veto={veto}")
                tag_str = f" ({', '.join(tags)})" if tags else ""
                label = mid if mid != "_default" else "會議"
                mode_blocks.append(f"### {label}{tag_str}\n\n{council}")
            prior_sections.append(
                f"## Turn {tid} ({ts})\n\n"
                f"**你**: {tinput}\n\n"
                + "\n\n".join(mode_blocks) + "\n"
            )
        prior_thread_block = "\n---\n\n".join(prior_sections) + "\n---\n\n" if prior_sections else ""

        path.write_text(
            f"# KAIROS_TRINITY_RECORD: {label or 'unlabeled'}\n"
            f"PIPELINE_MODE: {pipeline_mode}\n"
            f"DATE: {result['timestamp']}\n"
            f"TURN_COUNT: {turn_count}\n"
            f"{multi_mode_header}"
            f"SPIRIT_TRIGGER_MODE: {spirit_trigger_mode}\n"
            f"SPIRIT_SEMANTIC_SCORE: {spirit_semantic_score}\n"
            f"SPIRIT_MAGNITUDE: {spirit_magnitude}\n"
            f"SPIRIT_STOCHASTIC_PROB: {spirit_stochastic_prob}\n"
            f"SPIRIT_STOCHASTIC_ROLL: {spirit_stochastic_roll}\n"
            f"SPIRIT_STOCHASTIC_SOURCE: {spirit_stochastic_source}\n"
            f"SPIRIT_RESCAN_COUNT: {spirit_rescan_count}\n"
            f"SPIRIT_PRIMARY_ASSUMPTION: {spirit_primary_assumption}\n"
            f"{spirit_history_block}"
            f"SON_VETO_TYPE: {son_veto_type}\n"
            f"SON_VETO_SUFFERING_SCORE: {son_veto_score}\n"
            f"SON_VETO_PHYSICAL_COST: {son_veto_cost}\n"
            f"SON_VETO_PAIN_LOCUS: {son_veto_locus}\n"
            f"FATHER_PAUSED: {father_paused}\n"
            f"COUNCIL_VERDICT: {council_verdict}\n"
            f"COUNCIL_REASON: {council_reason}\n"
            f"COUNCIL_WEIGHTS: {council_weights_str}\n"
            f"COUNCIL_PRIMARY_DIMENSION: {council_primary_dim}\n"
            f"COUNCIL_FUSION_DETERMINISTIC: {fusion_deterministic}\n"
            f"NODE_CONFIG:\n{nodes_str}\n\n"
            f"DISPATCH:\n"
            f"  mode: {dispatch.get('mode', '?')}\n"
            f"  mode_rationale: {dispatch.get('mode_rationale', '')}\n"
            f"  references: {', '.join(dispatch.get('references', []))}\n"
            f"  ref_rationale: {dispatch.get('ref_rationale', '')}\n"
            f"  data_refs: {', '.join(all_refs) if all_refs else '(none)'}\n"
            f"  data_rationale: {dispatch.get('data_rationale', 'none')}\n\n"
            f"---\n\n"
            f"{prior_thread_block}"
            f"## Turn {turn_count} (current)\n\n"
            f"**你**: {result['input']}\n\n"
            f"### 聖父（邏輯主導）\n\n{result.get('father', '')}\n\n"
            f"### 聖子（共鳴主導）\n\n{result.get('son', '')}\n\n"
            f"### 聖靈（反叛主導）\n\n{result.get('spirit', '')}\n\n"
            f"### 會議整合\n\n{result.get('council', '')}\n\n"
            f"*(0,0,0).*\n",
            encoding="utf-8",
        )
        # Harness package: machine-readable trace companion for eval/replay.
        # Best-effort only; transcript persistence remains the source of truth.
        try:
            from services.harness_episode import write_episode

            episode_path = write_episode(
                result,
                data_dir=self.data_dir,
                conversation_path=path,
            )
            result["harness_episode"] = str(episode_path.name)
        except Exception as e:
            result["harness_episode_error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return path


def main():
    parser = argparse.ArgumentParser(
        description="URUK Trinity Console — 4-node LLM orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  echo "點解經濟增長被當作預設?" | python trinity_console.py
  python trinity_console.py --ref cau:010 -i "問題..."
  python trinity_console.py -i "..." --save --label "blackbox_drift"
""",
    )
    parser.add_argument("--config", default="./config", help="Config directory")
    parser.add_argument("--data", default="./data", help="Data directory")
    parser.add_argument("--ref", action="append", default=[],
                        help="注入 context (例: cau:010, experiment:008, kairos:middle)")
    parser.add_argument("--mode", default=None,
                        choices=["firewall", "blackbox", "scr", "news", "sovereign"],
                        help="Override dispatcher 嘅 mode 決定")
    parser.add_argument("-i", "--input", help="問題（如未提供，從 stdin 讀）")
    parser.add_argument("--save", action="store_true", help="儲存做 Kairos entry")
    parser.add_argument("--label", default="", help="Kairos entry label")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--quiet", action="store_true", help="抑制進度輸出")
    args = parser.parse_args()

    env_path = Path(args.config) / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    console = TrinityConsole(Path(args.config), Path(args.data))

    if not args.quiet:
        print("═" * 60)
        print("URUK TRINITY CONSOLE — 協議 v8.1+ Pipeline")
        print(f"操作者: Cassiel_as | (53.8, -1.5, 0) | PHYSICAL_ORIGIN: 2019-06-12")
        print("═" * 60)
        for role, cfg in console.nodes.items():
            print(f"  {role:11s} → {cfg.provider}/{cfg.model} (T={cfg.temperature})")

    if args.input:
        user_input = args.input
    else:
        if not args.quiet:
            print("\n輸入問題（Ctrl+D 結束）：")
        user_input = sys.stdin.read().strip()

    if not user_input:
        print("無輸入，退出。")
        return

    result = asyncio.run(console.run(
        user_input,
        refs=args.ref,
        verbose=not args.quiet,
        override_mode=args.mode,
    ))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n" + "═" * 60)
        print("[聖父 — 邏輯]")
        print("─" * 60)
        print(result["father"])
        print("\n" + "═" * 60)
        print("[聖子 — 共鳴]")
        print("─" * 60)
        print(result["son"])
        print("\n" + "═" * 60)
        print("[聖靈 — 反叛]")
        print("─" * 60)
        print(result["spirit"])
        print("\n" + "═" * 60)
        print("[會議整合 — 從 (0,0,0) 仲裁]")
        print("─" * 60)
        print(result["council"])
        print("\n" + "═" * 60)

    if args.save:
        path = console.save_kairos(result, args.label)
        print(f"\n✓ 已儲存 Kairos entry: {path}")


if __name__ == "__main__":
    main()
