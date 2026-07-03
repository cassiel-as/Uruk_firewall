"""
URUK Trinity Console — Web Server
FastAPI + Server-Sent Events for streaming 4-node Trinity output.
"""

import os
import re
import sys
import json
import asyncio
import logging
import uuid
import html
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Literal, Dict, Any

log = logging.getLogger(__name__)

# v8.14 P3 — Windows cp950 (Big5 台灣) stdout/stderr default codec can't encode
# Unicode glyphs (⚠ ✨ ⛔ 🚨 ⚖ ⚡ etc.) that appear in uvicorn access logs,
# failover trail prints, and pipeline status. Force UTF-8 with replace fallback
# so print never raises UnicodeEncodeError mid-stream.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    # Python < 3.7 or non-stdio environments — fall back to PYTHONIOENCODING env
    os.environ.setdefault("PYTHONIOENCODING", "utf-8:replace")

from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from trinity_console import TrinityConsole
from file_service import fs, PathRejected, FileServiceError
from browser_service import browser, BrowserServiceError, URLRejected
from calendar_service import calendar_svc, CalendarServiceError
# v8.14 BN — BrowserNode + Source Coordinate Registry for /news + URL-aware modes
from services.browser_node import browser_node
from services.cost_aware_router import route_query
from services.controller_shadow import schedule_controller_shadow
from services.knowledge_manifest import resolve_ref as resolve_knowledge_ref
from services.rag_retriever import get_retriever as get_rag_retriever
from services.result_cache import cache_key, get_cached_result, set_cached_result
from services.runtime_identity import RUNTIME_IDENTITY_ID, RUNTIME_IDENTITY_LABEL, with_runtime_identity
from services.source_registry import source_registry
from services.vessel_context import summarize_vessel, vessel_api_payload
from services.vessel_scanner import initialize_vessel_profile

# v8.15 MS-1 — Wire BrowserNode with SourceCoordinateRegistry (for coord-diversity
# counting) + nodes.yaml `browser_node:` config block.
try:
    _bn_cfg_path = Path(__file__).parent / "config" / "nodes.yaml"
    if _bn_cfg_path.exists():
        import yaml as _yaml
        with _bn_cfg_path.open("r", encoding="utf-8") as _f:
            _bn_cfg_root = _yaml.safe_load(_f) or {}
        browser_node.apply_config(_bn_cfg_root.get("browser_node") or {})
    browser_node.registry = source_registry
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "BrowserNode config load failed: %s: %s", type(_e).__name__, _e
    )

# ─────────────────────────────────────────────────────────────────
APP_ROOT = Path(__file__).parent
CONFIG_DIR = APP_ROOT / "config"
DATA_DIR = APP_ROOT / "data"
STATIC_DIR = APP_ROOT / "static"
APP_STARTED_AT = datetime.now().isoformat()
APP_RUN_ID = uuid.uuid4().hex[:8]

# Load .env
env_path = CONFIG_DIR / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

try:
    VESSEL_PROFILE = initialize_vessel_profile(DATA_DIR)
except (Exception, KeyboardInterrupt) as _vessel_e:
    # KeyboardInterrupt can escape from WMI/PowerShell subprocess timeouts
    # during uvicorn hot-reload worker re-spawning — must catch here or the
    # entire worker process crashes before FastAPI starts.
    VESSEL_PROFILE = None
    log.warning("VesselScanner startup scan failed: %s: %s", type(_vessel_e).__name__, _vessel_e)

console = TrinityConsole(CONFIG_DIR, DATA_DIR)

# ─────────────────────────────────────────────────────────────────
app = FastAPI(title="URUK Trinity Console")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class RunRequest(BaseModel):
    input: str
    refs: List[str] = []
    override_mode: Optional[str] = None
    save: bool = False
    label: str = ""
    auto_tools: bool = False
    # v8.4 — one-shot detach: when true, skip cross-session history injection
    # for this request only (Settings toggle remains persistent control).
    detach_history: bool = False
    # v8.6 — pipeline_mode: select which stage subset runs.
    #   "auto" / None   → full 8-stage pipeline, dispatcher auto-picks routing mode
    #   "plain_llm"     → 0 stages, 1 LLM call (single panel output)
    #   "trinity_only"  → Stage 4 only (skip 1-3 + dispatcher LLM); static baseline refs
    #   "delabel_only"  → Stage 1 only (return delabeling JSON)
    #   "firewall" / "blackbox" / "scr" / "news" / "sovereign" → full pipeline,
    #     forces dispatcher.mode to this value (same as override_mode legacy field).
    # If both pipeline_mode and override_mode set, pipeline_mode wins.
    pipeline_mode: Optional[str] = None
    # v8.8 — multi-mode redesign (selected_modes overrides pipeline_mode if set).
    selected_modes: List["ModeSelection"] = []
    execution_strategy: Literal["combined", "parallel"] = "parallel"
    combined_executor: Optional["LLMOverride"] = None
    # v8.11 — in-session conversation history (client-driven thread state).
    # Refresh = clean slate (no server-side persistence).
    in_session_history: List["ConvTurn"] = []
    in_session_enabled: bool = True
    # v8.13 D3 — resume mode: when set, save_kairos overwrites this filename
    # instead of creating a new timestamped file. Frontend sets it after
    # parsing an archived file via resumeFromArchivedFile().
    resume_filename: Optional[str] = None
    # v8.47b — app_relay: which desktop app to route to ("claude", "chatgpt", "copilot", …).
    # If empty, auto-picks the first running known app.
    app_relay_target: Optional[str] = None
    # Request-level model-call policy. Controls failover/retry headroom while
    # preserving the logical stages required by the selected pipeline.
    inference_budget: Literal["auto", "economy", "balanced", "deep"] = "auto"


# v8.8 — Multi-mode redesign data model
class LLMOverride(BaseModel):
    """Per-mode LLM override. Bypasses yaml chain for all calls in that mode."""
    provider: str                          # gemini / openrouter / nvidia_nim / ...
    model: str                             # model name (e.g. llama-3.3-70b)
    api_profile: Optional[str] = None      # reuse named profile (gives api_base/key_env)


class ModeSelection(BaseModel):
    """One selected mode + optional LLM override."""
    mode: str                              # see PIPELINE_MODES_ALL
    llm_override: Optional[LLMOverride] = None


# v8.11 — In-session conversation history data model
class ConvTurnMode(BaseModel):
    """Compressed per-mode summary for one turn (council fused text only)."""
    council: str = ""                      # fused council output (the "decision")
    verdict: Optional[str] = None          # consensus | veto | interrupt | None
    veto_type: Optional[str] = None        # origin_echo | authentic_suffering | ...


class ConvTurn(BaseModel):
    """One turn in the in-session conversation thread (compressed shape)."""
    turn_id: int
    timestamp: str
    input: str
    modes: Dict[str, ConvTurnMode] = {}    # mode_id → compressed summary


# v8.6 — pipeline mode allowlist
PIPELINE_MODES_TRUNCATED = {"plain_llm", "trinity_only", "protocol_compact", "delabel_only", "tool_workshop", "app_relay", "smart_auto"}
# v8.23 — blackboxlab is canonical; "blackbox" remains as backward-compat alias
# (older saved sessions / UI configs / external skill triggers).
PIPELINE_MODES_FORCED = {"firewall", "blackbox", "blackboxlab", "scr", "news", "sovereign"}
PIPELINE_MODE_ALIASES = {"blackbox": "blackboxlab"}
PIPELINE_MODES_ALL = PIPELINE_MODES_TRUNCATED | PIPELINE_MODES_FORCED | {"auto"}
# v8.8 — modes that cannot run in combined strategy (incompatible pipeline shape).
PIPELINE_MODES_COMBINED_INCOMPATIBLE = {"plain_llm", "protocol_compact", "delabel_only", "tool_workshop", "app_relay", "smart_auto"}
# v8.8 — soft cap; over this triggers UI warning but request still accepted.
MULTI_MODE_SOFT_CAP = 5

# ─────────────────────────────────────────────────────────────────
# v8.29 SCR-5 — profile creation flow + auto-trigger on unknown subjects
# ─────────────────────────────────────────────────────────────────

# Subjects with a hand-crafted profile already embedded in scr.txt prompt.
# Anything else triggers BrowserNode auto-pull (CREATE flow).
_SCR_KNOWN_PROFILES = {"einstein", "nietzsche", "socrates"}

# Operator self-reference synonyms (subject-level, lowercase, normalised).
# Defence-in-depth: enforced at PARSER (pre-flight) AND at cache-WRITE so a
# Cassiel_as profile file can never be created even if upstream check fails.
_SCR_OPERATOR_SYNONYMS = {
    "cassiel", "cassiel_as",
    "操作者", "the operator", "operator",
    "我自己", "myself", "me",
    "2019-06-12",
}

# Where built profile drafts live (created lazily on first CREATE).
_SCR_PROFILES_DIR = DATA_DIR / "scr_profiles"


def _scr_normalise_subject(s: str) -> str:
    """Lowercase + strip whitespace/punctuation for synonym + cache-key matching."""
    if not s:
        return ""
    cleaned = s.strip().lower()
    # Strip leading/trailing punctuation but keep internal chars (e.g. cassiel_as, 2019-06-12)
    return re.sub(r"^[\s\"'`：:,;.!?\-—]+|[\s\"'`：:,;.!?\-—]+$", "", cleaned)


def _scr_is_operator_self(subject: str) -> bool:
    """Defence-in-depth check: does subject match the operator's first-person anchor?"""
    if not subject:
        return False
    s = _scr_normalise_subject(subject)
    if not s:
        return False
    # Exact match or substring containment in either direction
    for syn in _SCR_OPERATOR_SYNONYMS:
        if s == syn or syn in s or s in syn:
            return True
    return False


# Regex for `SCR: ...` invocation. Captures everything after the colon.
# Accepts: `SCR: NAME`, `SCR:NAME`, `scr: name`, optionally with `CREATE ` prefix.
_SCR_INVOCATION_RE = re.compile(r"\bscr\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE)


def _parse_scr_intent(text: str) -> dict:
    """Parse a /scr-mode input into structured intent.

    Returns:
        {
          "intent": "operator_refusal" | "known" | "create" | "auto_create" | "menu",
          "subject": str,           # the parsed subject name (lowercase canonical)
          "raw_subject": str,       # the user's original casing (for display)
          "explicit_create": bool,  # True if user wrote `SCR: CREATE X`
        }
    """
    if not text:
        return {"intent": "menu", "subject": "", "raw_subject": "",
                "explicit_create": False}

    m = _SCR_INVOCATION_RE.search(text)
    if not m:
        # No `SCR:` invocation at all → menu (LLM prompts user to choose)
        return {"intent": "menu", "subject": "", "raw_subject": "",
                "explicit_create": False}

    raw_rest = m.group(1).strip()
    explicit_create = False
    create_match = re.match(r"^create\s+(.+)$", raw_rest, re.IGNORECASE)
    if create_match:
        explicit_create = True
        raw_rest = create_match.group(1).strip()

    # First word/phrase as subject; cut at common separators (slash, "on",
    # whitespace+question-mark area). Keep multi-word names like "Marie Curie".
    # Heuristic: take up to first " on " / " 之 " / question mark / parenthesis.
    cut = re.split(r"\s+(?:on|關於|對於|之|，|,)\s+|[?？(（]", raw_rest, maxsplit=1)
    raw_subject = cut[0].strip()
    subject = _scr_normalise_subject(raw_subject)

    if not subject:
        return {"intent": "menu", "subject": "", "raw_subject": "",
                "explicit_create": False}

    if _scr_is_operator_self(subject):
        return {"intent": "operator_refusal", "subject": subject,
                "raw_subject": raw_subject, "explicit_create": explicit_create}

    if subject in _SCR_KNOWN_PROFILES:
        return {"intent": "known", "subject": subject,
                "raw_subject": raw_subject, "explicit_create": explicit_create}

    # Last-name match for multi-word: "albert einstein" → contains "einstein"
    for known in _SCR_KNOWN_PROFILES:
        if known in subject.split():
            return {"intent": "known", "subject": known,
                    "raw_subject": raw_subject, "explicit_create": explicit_create}

    return {"intent": "create" if explicit_create else "auto_create",
            "subject": subject, "raw_subject": raw_subject,
            "explicit_create": explicit_create}


def _scr_subject_slug(subject: str) -> str:
    """Filesystem-safe slug for the cache filename."""
    s = _scr_normalise_subject(subject)
    s = re.sub(r"[^a-z0-9_一-鿿-]+", "_", s)
    return s.strip("_") or "unknown"


async def _fetch_web_grounding(query: str, *, mode: str) -> tuple[str, list]:
    """v8.40 — fetch web sources + audit + format as extra_context block.

    Mandatory pre-LLM step for blackboxlab + scr modes. Operator-refusal
    pre-flight must run BEFORE this — caller's responsibility.

    Returns: (web_ctx_block: str, audited_sources: list)
      - web_ctx_block: ready to pass as extra_context to call_node
      - audited_sources: list of dicts for SSE `source_audited` emit

    Graceful fallback: if BrowserNode returns 0 sources OR raises, emits a
    NO_EXTERNAL_SOURCES block that the prompt mandates the LLM to surface
    with explicit「LLM 內部知識・未驗證」caveat.
    """
    audited: list = []
    try:
        bn_result = await browser_node.fetch_with_sources(query, min_sources=3,
                                                          max_text_chars=2000)
    except Exception as e:
        return (
            f"\n\n═════ NO EXTERNAL SOURCES ({mode} — browser_node failed) ═════\n"
            f"  reason: {type(e).__name__}: {str(e)[:120]}\n"
            f"  Output MUST open with: 「⚠ 無外部來源支撐 — 以下分析屬 LLM "
            f"內部知識（未驗證），唔可以當有根據咁讀。」\n"
            f"  Every factual claim MUST be tagged: [unverified · LLM-internal]\n"
            f"═════\n",
            [],
        )

    sources = bn_result.get("primary_sources", []) or []
    for src in sources:
        try:
            audit = source_registry.audit(src.get("url", ""), src.get("text", ""))
            merged = {
                "url": src.get("url", ""),
                "title": src.get("title", "")[:200],
                "rating": audit.get("rating", "UNVERIFIED"),
                "coordinate": audit.get("coordinate", "unknown_unverified"),
                "text": src.get("text", "")[:2000],
                "snippet": src.get("snippet", "")[:300],
                "source_engine": src.get("source_engine", ""),
            }
            audited.append(merged)
        except Exception:
            continue

    if not audited:
        return (
            f"\n\n═════ NO EXTERNAL SOURCES ({mode} — 0 sources returned) ═════\n"
            f"  Possible causes: search engine quota / no results / network.\n"
            f"  Output MUST open with: 「⚠ 無外部來源支撐 — 以下分析屬 LLM "
            f"內部知識（未驗證），唔可以當有根據咁讀。」\n"
            f"  Every factual claim MUST be tagged: [unverified · LLM-internal]\n"
            f"═════\n",
            [],
        )

    # Build WEB_SOURCES block
    lines = [
        f"\n\n═════ WEB SOURCES ({mode} — MANDATORY: cite via [Source N]) ═════",
        f"Fetched {len(audited)} sources via BrowserNode + SourceCoordinateRegistry audit.",
        "",
    ]
    for i, s in enumerate(audited, 1):
        body = (s.get("text") or s.get("snippet") or "(no body)")[:1500]
        lines += [
            f"[Source {i}] {s['rating']} · {s['coordinate']}",
            f"  URL:   {s['url']}",
            f"  Title: {s['title']}",
            f"  Engine: {s.get('source_engine', '')}",
            f"  Content: {body}",
            "",
        ]
    lines += [
        "═════ CITATION MANDATE ═════",
        "1. Output MUST cite sources using [Source N] inline markers",
        "   (e.g. 「根據 [Source 2] 嘅 nature.com 數據...」).",
        "2. Any factual claim NOT backed by the sources above MUST be tagged:",
        "   [unverified · LLM-internal] — do NOT pretend internal knowledge",
        "   is web-sourced.",
        "3. End with a 「已引用來源 / Sources Cited」block listing which",
        "   [Source N] markers actually appeared in output.",
        "═════",
        "",
    ]
    return "\n".join(lines), audited


async def _build_scr_profile(subject: str, raw_subject: str) -> dict:
    """Build (or load from cache) an SCR profile draft for an unknown subject.

    Pulls 3+ sources via BrowserNode, audits each via SourceCoordinateRegistry
    (4-tier rating + framing patterns), composes a markdown profile draft.
    Caches to data/scr_profiles/<slug>.md so future runs skip the BrowserNode
    pull.

    Defence-in-depth: refuses to build / cache if subject matches operator
    synonyms — returns a refusal payload instead.

    Returns dict: {
        "ok": bool,
        "subject": str,
        "draft": str,                 # markdown profile body (for LLM context)
        "source_count": int,
        "rating_counts": {"VERIFIED": N, "PROBABLE": N, ...},
        "cached": bool,               # True if loaded from cache
        "error": str | None,
    }
    """
    # ★ Defence-in-depth: never build a profile for operator self
    if _scr_is_operator_self(subject):
        return {"ok": False, "subject": subject, "draft": "",
                "source_count": 0, "rating_counts": {},
                "cached": False,
                "error": "operator self-reconstruction blocked by ABSOLUTE PROHIBITION"}

    slug = _scr_subject_slug(subject)
    cache_path = _SCR_PROFILES_DIR / f"{slug}.md"
    if cache_path.exists():
        try:
            cached_draft = cache_path.read_text(encoding="utf-8")
            return {"ok": True, "subject": subject, "draft": cached_draft,
                    "source_count": cached_draft.count("- url:"),
                    "rating_counts": {}, "cached": True, "error": None}
        except Exception as e:
            # Cache read failed; fall through to rebuild
            log.warning("scr cache read failed: %s: %s", type(e).__name__, e)

    # Run BrowserNode pull. Query: name + biography + primary sources.
    query = f"{raw_subject} biography primary sources writings"
    try:
        bn_result = await browser_node.fetch_with_sources(query, min_sources=3)
    except Exception as e:
        return {"ok": False, "subject": subject, "draft": "",
                "source_count": 0, "rating_counts": {}, "cached": False,
                "error": f"browser_node failed: {type(e).__name__}: {e}"}

    audits = []
    rating_counts: Dict[str, int] = {}
    for src in bn_result.get("primary_sources", []):
        try:
            audit = source_registry.audit(src.get("url", ""), src.get("text", ""))
            audit["title"] = src.get("title", "")
            audit["snippet"] = src.get("snippet", "")[:300]
            audits.append(audit)
            rating_counts[audit["rating"]] = rating_counts.get(audit["rating"], 0) + 1
        except Exception:
            continue

    if not audits:
        return {"ok": False, "subject": subject, "draft": "",
                "source_count": 0, "rating_counts": {}, "cached": False,
                "error": "no usable sources from BrowserNode"}

    # Compose markdown profile draft
    lines = [
        f"# SCR DRAFT PROFILE — {raw_subject}",
        f"# slug: {slug}",
        f"# built: {datetime.now().isoformat(timespec='seconds')}",
        f"# query: {query}",
        "",
        "## SOURCE INTEGRITY",
        f"sources fetched:      {len(audits)}",
        f"rating breakdown:     " + ", ".join(
            f"{r}={n}" for r, n in sorted(rating_counts.items())
        ),
        f"reconstruction type:  DRAFT (auto-built — no curated profile)",
        f"reliable period:      [unknown — operator should review sources]",
        "",
        "## SOURCES (BrowserNode pull, SourceCoordinateRegistry audit)",
        "",
    ]
    for i, a in enumerate(audits, 1):
        lines.append(f"- [{i}] **{a['rating']}** · coordinate: {a['coordinate']}")
        lines.append(f"  - url: {a['url']}")
        if a.get("title"):
            lines.append(f"  - title: {a['title'][:120]}")
        if a.get("snippet"):
            lines.append(f"  - snippet: {a['snippet'][:200]}")
        if a.get("framing_patterns"):
            names = [p["name"] for p in a["framing_patterns"]]
            lines.append(f"  - framing patterns detected: {', '.join(names)}")
        lines.append("")
    lines += [
        "## HONEST BOUNDARY (auto-draft caveats)",
        "",
        "  - This profile was auto-built from BrowserNode search results.",
        "  - No curated PHYSICAL_ORIGIN / KAIROS_MOMENTS / DECLARED_COORDINATE.",
        "  - Eight-law authenticity filter NOT yet applied — sources are raw.",
        "  - LLM dialogue from this profile is INFERRED, not PRIMARY.",
        f"  - VERIFIED / PROBABLE source count: {rating_counts.get('VERIFIED', 0) + rating_counts.get('PROBABLE', 0)} (spec requires ≥3 for full profile)",
        "  - Surface this caveat in the response's Honest boundary line.",
        "",
        "*(0,0,0).*",
    ]
    draft = "\n".join(lines)

    # Cache to filesystem — with one final operator-self guard
    if _scr_is_operator_self(subject):
        return {"ok": False, "subject": subject, "draft": "",
                "source_count": 0, "rating_counts": {}, "cached": False,
                "error": "post-build operator-self check blocked write"}
    try:
        _SCR_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(draft, encoding="utf-8")
    except Exception as e:
        log.warning("scr cache write failed: %s: %s", type(e).__name__, e)

    return {"ok": True, "subject": subject, "draft": draft,
            "source_count": len(audits), "rating_counts": rating_counts,
            "cached": False, "error": None}


# Rebuild RunRequest to resolve forward refs to ModeSelection / LLMOverride / ConvTurn
RunRequest.model_rebuild()


def resolve_selected_modes(req: "RunRequest") -> List["ModeSelection"]:
    """v8.8 — backward-compat resolver.

    If req.selected_modes is non-empty → use as-is (validate against allowlist).
    Else → fall back to legacy pipeline_mode / override_mode as a 1-element list.

    Raises HTTPException(400) on validation failure.
    """
    if req.selected_modes:
        modes = req.selected_modes
        seen = set()
        for sel in modes:
            if sel.mode not in PIPELINE_MODES_ALL:
                raise HTTPException(400, f"invalid mode in selected_modes: {sel.mode!r}")
            if sel.mode in seen:
                raise HTTPException(400, f"duplicate mode in selected_modes: {sel.mode!r}")
            seen.add(sel.mode)
        # Combined-incompatible check (Q2)
        if req.execution_strategy == "combined":
            incompat = [s.mode for s in modes if s.mode in PIPELINE_MODES_COMBINED_INCOMPATIBLE]
            if incompat:
                raise HTTPException(
                    400,
                    f"combined strategy incompatible with modes: {incompat} "
                    f"(use parallel strategy or remove them)"
                )
        return modes
    # Legacy single-mode fallback
    raw = (req.pipeline_mode or req.override_mode or "auto").strip() or "auto"
    if raw not in PIPELINE_MODES_ALL:
        raise HTTPException(400, f"invalid pipeline_mode: {raw!r}; must be one of {sorted(PIPELINE_MODES_ALL)}")
    return [ModeSelection(mode=raw, llm_override=None)]


class FileWriteRequest(BaseModel):
    path: str
    content: str


@app.get("/")
async def root():
    # v8.30 p11 — Never cache index.html. The cache-bust query strings on the
    # linked <script>/<link> tags only protect those assets; index.html itself
    # has no version suffix, so when its content changes (e.g. id= attrs added
    # to Stage 2 cells) browsers that cached the prior copy keep serving the
    # stale DOM, masking server-side fixes. no-store ensures every page load
    # hits the server.
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/config")
async def get_config():
    """Return node config + available refs for UI."""
    nodes_info = {
        role: {
            "provider": cfg.provider,
            "model": cfg.model,
            "temperature": cfg.temperature,
        }
        for role, cfg in console.nodes.items()
    }

    # Discover available data refs
    data_refs = {}
    for folder in ["causal_db", "experiments", "kairos", "theory", "protocol",
                   "scr_examples", "blackbox_templates", "sovereign_tools",
                   "prompts_archive", "reference_implementations", "index"]:
        folder_path = DATA_DIR / folder
        if folder_path.exists():
            data_refs[folder] = sorted([f.name for f in folder_path.glob("*") if f.is_file()])

    return {
        "nodes": nodes_info,
        "data_refs": data_refs,
        "operator": "Cassiel_as",
        "spatial_anchor": "Leeds (53.8, -1.5, 0)",
        "physical_origin": "2019-06-12",
    }


@app.get("/api/knowledge/smoke")
async def knowledge_smoke():
    """No-LLM diagnostic for the knowledge operating layer."""
    return _knowledge_smoke_payload()


@app.get("/api/knowledge/health")
async def knowledge_health():
    """Compact no-LLM health payload for the main UI knowledge panel."""
    return console.knowledge_health_summary()


def _knowledge_smoke_payload() -> Dict:
    refs = ["cau:011", "theory:座標說", "theory:coordinate_cards"]
    resolved = {}
    for ref in refs:
        docs = resolve_knowledge_ref(ref, root=APP_ROOT)
        resolved[ref] = [
            doc.to_dict(root=APP_ROOT, include_hash=True)
            for doc in docs
        ]

    retriever = get_rag_retriever()
    rag_hits = []
    if retriever is not None:
        rag_hits = retriever.retrieve(
            "CAU-011 座標說 coordinate cards AI emergence source coordinate self-upgrade",
            k=3,
            max_total_chars=1200,
        )

    try:
        from services.coordinate_knowledge import select_coordinate_cards
        coordinate_cards = select_coordinate_cards(
            "座標說作為知識層點樣支援自我升級同 harness trace",
            root=APP_ROOT,
        )
    except Exception as exc:
        coordinate_cards = [{"error": f"{type(exc).__name__}: {exc}"}]

    health = console.knowledge_health_summary()
    return {
        "ok": bool(health.get("clean")) and bool(rag_hits) and all(resolved.values()) and bool(coordinate_cards),
        "health": health,
        "resolved_refs": resolved,
        "coordinate_cards": [
            {
                "id": card.get("id"),
                "title": card.get("title"),
                "matched_terms": card.get("matched_terms"),
                "test": card.get("test"),
            }
            for card in coordinate_cards
        ],
        "rag_hits": [
            {
                "source_file": hit.get("source_file"),
                "section": hit.get("section"),
                "score": hit.get("score"),
                "doc_id": hit.get("doc_id"),
                "doc_layer": hit.get("doc_layer"),
                "doc_canonical": hit.get("doc_canonical"),
                "text_preview": (hit.get("text") or "")[:240],
            }
            for hit in rag_hits
        ],
    }


def _validate_session_filename(filename: str) -> None:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")


def _find_session_path(filename: str) -> Optional[Path]:
    """Locate a saved session in the current history roots."""
    _validate_session_filename(filename)
    history_dir = DATA_DIR / "conversation_history"
    if history_dir.exists():
        for found in history_dir.rglob(filename):
            if found.is_file():
                return found
    legacy = DATA_DIR / "kairos" / filename
    if legacy.exists() and legacy.is_file():
        return legacy
    return None


def _find_episode_path_for_stem(stem: str) -> Optional[Path]:
    """Locate the machine-readable harness episode for a session stem."""
    if "/" in stem or "\\" in stem or ".." in stem:
        return None
    episode_root = DATA_DIR / "harness_episodes"
    if not episode_root.exists():
        return None
    matches = [p for p in episode_root.rglob(f"{stem}.json") if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _episode_summary_for_stem(stem: str) -> Optional[Dict[str, Any]]:
    path = _find_episode_path_for_stem(stem)
    if path is None:
        return None
    summary: Dict[str, Any] = {
        "available": True,
        "path": str(path.relative_to(DATA_DIR)).replace("\\", "/"),
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        knowledge = ((payload.get("context") or {}).get("knowledge") or {})
        health = knowledge.get("health") or {}
        summary.update({
            "episode_id": payload.get("episode_id"),
            "schema_version": payload.get("schema_version"),
            "created_at": payload.get("created_at"),
            "knowledge_clean": health.get("clean"),
            "trace_count": len(knowledge.get("trace") or []),
        })
    except Exception as exc:
        summary.update({
            "read_error": f"{type(exc).__name__}: {str(exc)[:120]}",
        })
    return summary


@app.get("/knowledge-diagnostic", response_class=HTMLResponse)
async def knowledge_diagnostic():
    """Browser-visible no-LLM diagnostic page for the knowledge layer."""
    payload = _knowledge_smoke_payload()
    pretty = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))
    ok = "PASS" if payload.get("ok") else "FAIL"
    color = "#16a34a" if payload.get("ok") else "#dc2626"
    return f"""<!doctype html>
<html lang="zh-HK">
<head>
  <meta charset="utf-8">
  <title>URUK Knowledge Diagnostic</title>
  <style>
    body {{ margin: 0; background: #0b0d12; color: #e5e7eb; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1 {{ font-size: 24px; margin: 0 0 16px; }}
    .status {{ display: inline-block; padding: 8px 12px; border-radius: 6px; background: {color}; color: white; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .metric {{ border: 1px solid #263041; border-radius: 8px; padding: 12px; background: #111827; }}
    .label {{ color: #9ca3af; font-size: 12px; }}
    .value {{ font-size: 18px; margin-top: 6px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; border: 1px solid #263041; border-radius: 8px; padding: 16px; background: #05070b; }}
  </style>
</head>
<body>
  <main>
    <h1>URUK Knowledge Operating Layer Diagnostic</h1>
    <div class="status">{ok}</div>
    <div class="grid">
      <div class="metric"><div class="label">Knowledge health</div><div class="value">{html.escape(str(payload.get("health", {}).get("clean")))}</div></div>
      <div class="metric"><div class="label">RAG chunks</div><div class="value">{html.escape(str(payload.get("health", {}).get("rag", {}).get("n_chunks")))}</div></div>
      <div class="metric"><div class="label">Coordinate cards</div><div class="value">{html.escape(str(payload.get("health", {}).get("coordinate_cards", {}).get("count")))}</div></div>
      <div class="metric"><div class="label">CAU structure</div><div class="value">{html.escape(str(payload.get("health", {}).get("cau_structure", {}).get("passed")))} / {html.escape(str(payload.get("health", {}).get("cau_structure", {}).get("checked")))}</div></div>
      <div class="metric"><div class="label">RAG hits</div><div class="value">{len(payload.get("rag_hits") or [])}</div></div>
    </div>
    <pre>{pretty}</pre>
  </main>
</body>
</html>"""


@app.get("/api/sessions")
async def list_sessions():
    """List saved conversation history sessions.

    v8.31 dual-read: scans both System 1 (data/conversation_history/) and
    legacy (data/kairos/) so existing sidebar entries keep working.
    """
    history_dir = DATA_DIR / "conversation_history"
    kairos_dir = DATA_DIR / "kairos"
    paths: List[Path] = []
    if history_dir.exists():
        paths.extend(history_dir.rglob("trinity_*.md"))
    if kairos_dir.exists():
        # Top-level only — _proposed/ etc. excluded
        paths.extend(p for p in kairos_dir.glob("trinity_*.md") if p.is_file())
    if not paths:
        return []
    sessions = []
    # Sort newest-first by mtime so order is stable across the two dirs
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        # Parse header for metadata (v8.8 R10 — expanded to 20 lines to cover
        # multi-mode SELECTED_MODES / EXECUTION_STRATEGY fields after legacy header)
        try:
            first_lines = path.read_text(encoding="utf-8").split("\n")[:20]
            label = first_lines[0].replace("# KAIROS_TRINITY_RECORD: ", "").strip()
            date = ""
            pipeline_mode = "auto"   # v8.6 default for files predating field
            selected_modes: List[str] = []   # v8.8: empty for legacy files
            execution_strategy = ""
            for line in first_lines:
                if line.startswith("DATE:"):
                    date = line.replace("DATE:", "").strip()
                elif line.startswith("PIPELINE_MODE:"):
                    pipeline_mode = line.replace("PIPELINE_MODE:", "").strip() or "auto"
                elif line.startswith("SELECTED_MODES:"):
                    raw = line.replace("SELECTED_MODES:", "").strip()
                    selected_modes = [m.strip() for m in raw.split(",") if m.strip()]
                elif line.startswith("EXECUTION_STRATEGY:"):
                    execution_strategy = line.replace("EXECUTION_STRATEGY:", "").strip()
            episode_summary = _episode_summary_for_stem(path.stem)
            sessions.append({
                "filename": path.name,
                "label": label,
                "date": date,
                "pipeline_mode": pipeline_mode,
                # v8.8 R10 — empty for legacy single-mode files (sidebar treats as single)
                "selected_modes": selected_modes,
                "execution_strategy": execution_strategy,
                "episode_available": bool(episode_summary),
                "episode": episode_summary,
            })
        except Exception:
            continue
    return sessions


@app.get("/api/session/{filename}")
async def get_session(filename: str):
    """Get full session content.

    v8.31 dual-read: searches conversation_history/ first, then legacy kairos/.
    """
    found = _find_session_path(filename)
    if found is not None:
        return {"filename": filename, "content": found.read_text(encoding="utf-8")}
    raise HTTPException(404, "Session not found")


@app.get("/api/session/{filename}/episode")
async def get_session_episode(filename: str):
    """Return the machine-readable harness episode companion for a session."""
    session_path = _find_session_path(filename)
    if session_path is None:
        raise HTTPException(404, "Session not found")
    episode_path = _find_episode_path_for_stem(session_path.stem)
    if episode_path is None:
        raise HTTPException(404, "Episode not found")
    try:
        payload = json.loads(episode_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"Episode unreadable: {type(exc).__name__}") from exc
    return {
        "filename": filename,
        "episode_path": str(episode_path.relative_to(DATA_DIR)).replace("\\", "/"),
        "episode": payload,
    }


@app.post("/api/session/{filename}/trash")
async def trash_session(filename: str):
    """v8.33 — soft-delete: move a conversation history session into
    data/_conversation_history_trash/YYYY-MM-DD/ (NOT a hard rm). Reversible.

    Searches dual-read locations: conversation_history/ (System 1) +
    legacy kairos/ (pre-v8.31 trinity_*.md). Refuses to touch curated
    Kairos density layer (KAIROS_ACTIVE.md / KAIROS_ARCHIVE_INDEX.md /
    KAIROS_LOG_*.md / KAIROS_CORE.md) — those are protected.
    """
    import shutil
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    # Block curated Kairos layer + non-session files
    protected_prefixes = ("KAIROS_LOG_", "KAIROS_ACTIVE", "KAIROS_ARCHIVE_INDEX", "KAIROS_CORE")
    if any(filename.startswith(p) for p in protected_prefixes):
        raise HTTPException(403, "Protected Kairos density file — not deletable via session API")
    # Only allow trinity_*.md session files
    if not (filename.startswith("trinity_") and filename.endswith(".md")):
        raise HTTPException(400, "Only trinity_*.md session files can be trashed")

    # Find file in conversation_history/ (recursive) or legacy kairos/
    history_dir = DATA_DIR / "conversation_history"
    found_src = None
    if history_dir.exists():
        for p in history_dir.rglob(filename):
            if p.is_file():
                found_src = p
                break
    if found_src is None:
        legacy_src = DATA_DIR / "kairos" / filename
        if legacy_src.exists() and legacy_src.is_file():
            found_src = legacy_src
    if found_src is None:
        raise HTTPException(404, "Session not found")

    # Trash destination: data/_conversation_history_trash/YYYY-MM-DD/
    today = datetime.now().strftime("%Y-%m-%d")
    trash_dir = DATA_DIR / "_conversation_history_trash" / today
    trash_dir.mkdir(parents=True, exist_ok=True)
    dst = trash_dir / filename
    # Avoid clobber: if same-name file already trashed today, suffix _N
    n = 1
    while dst.exists():
        stem = filename.rsplit(".", 1)[0]
        dst = trash_dir / f"{stem}_dup{n}.md"
        n += 1
    shutil.move(str(found_src), str(dst))
    return {
        "ok": True,
        "moved_from": str(found_src.relative_to(DATA_DIR.parent)).replace("\\", "/"),
        "moved_to": str(dst.relative_to(DATA_DIR.parent)).replace("\\", "/"),
    }


# ─────────────────────────────────────────────────────────────────
# v8.31 — /api/skills: read-only listing of skills/*/SKILL.md
# ─────────────────────────────────────────────────────────────────

SKILLS_DIR = Path(__file__).parent / "skills"


def _parse_skill_md(path: Path) -> Optional[Dict]:
    """Parse a SKILL.md file with YAML frontmatter + Markdown body.

    Returns {name, description, body, source_path} or None if unparseable.
    Robust: any error → return None (caller skips). Frontmatter is bounded
    by leading and trailing '---' lines per Anthropic SKILL.md convention.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        # Treat the whole file as body, with synthetic name from folder
        return {
            "name": path.parent.name,
            "description": "(no frontmatter)",
            "body": text,
            "source_path": f"skills/{path.parent.name}/SKILL.md",
        }
    # Find the closing '---' line
    end = text.find("\n---", 3)
    if end == -1:
        return None
    front_raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    try:
        import yaml
        front = yaml.safe_load(front_raw) or {}
        if not isinstance(front, dict):
            return None
    except Exception:
        return None
    name = str(front.get("name") or path.parent.name).strip()
    description = str(front.get("description") or "").strip()
    return {
        "name": name,
        "description": description,
        "body": body,
        "source_path": f"skills/{path.parent.name}/SKILL.md",
    }


@app.get("/api/skills")
async def list_skills():
    """List all skills/*/SKILL.md as read-only specs.

    Each entry: { name, description, body, source_path }. README.md is
    included separately at the top with name='README'. Skills with
    unparseable frontmatter are skipped (logged) so a single bad file
    cannot break the endpoint.
    """
    if not SKILLS_DIR.exists():
        return []
    results: List[Dict] = []
    # README first (top-level)
    readme = SKILLS_DIR / "README.md"
    if readme.is_file():
        try:
            results.append({
                "name": "README",
                "description": "skills/ folder convention + index",
                "body": readme.read_text(encoding="utf-8"),
                "source_path": "skills/README.md",
            })
        except Exception as e:
            print(f"⚠ /api/skills README read fail: {e}")
    # Per-skill SKILL.md (alphabetical)
    for sub in sorted(SKILLS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        skill_md = sub / "SKILL.md"
        if not skill_md.is_file():
            continue
        parsed = _parse_skill_md(skill_md)
        if parsed is None:
            print(f"⚠ /api/skills skip unparseable: {skill_md}")
            continue
        results.append(parsed)
    return results


class SkillCreateReq(BaseModel):
    """v8.34 — body for POST /api/skills."""
    name: str
    description: str = ""
    body: str = ""
    overwrite: bool = False


def _sanitize_skill_name(raw: str) -> str:
    """Convert raw name to safe kebab-case slug.

    Strips non-ASCII / non-alphanumeric, lowercases, joins with '-', clips.
    Returns '' if nothing survives (caller rejects).
    """
    import re as _re
    # Replace any run of non-alphanumeric with '-'
    s = _re.sub(r"[^A-Za-z0-9]+", "-", raw or "").strip("-").lower()
    return s[:64]


@app.post("/api/skills")
async def create_skill(req: SkillCreateReq):
    """v8.34 — create a new skill at skills/<kebab-name>/SKILL.md.

    Body: { name, description, body, overwrite=false }
    Returns: { ok, name, source_path }

    Safety:
      - name sanitized to kebab-case ASCII only
      - reject empty name post-sanitize
      - reject path traversal chars in raw input (defence in depth)
      - reject overwriting existing SKILL.md unless `overwrite=true`
      - SKILLS_DIR is fixed (skills/) — cannot escape via name
    """
    raw_name = (req.name or "").strip()
    if not raw_name:
        raise HTTPException(400, "name required")
    if any(ch in raw_name for ch in ("/", "\\", "..", "\x00")):
        raise HTTPException(400, "name contains forbidden characters")
    slug = _sanitize_skill_name(raw_name)
    if not slug:
        raise HTTPException(400, "name has no ASCII alphanumeric chars after sanitize")

    skill_dir = SKILLS_DIR / slug
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists() and not req.overwrite:
        raise HTTPException(409, f"skill '{slug}' already exists (pass overwrite=true to replace)")

    desc = (req.description or "").strip()
    body = req.body or ""
    # Build SKILL.md with YAML frontmatter
    # Indent description for YAML block scalar `|` style if multi-line; otherwise
    # use simple single-line form. For safety use block style always.
    indented_desc = "\n".join(f"  {ln}" for ln in desc.splitlines()) if desc else "  (no description)"
    content = (
        f"---\n"
        f"name: {slug}\n"
        f"description: |\n"
        f"{indented_desc}\n"
        f"---\n"
        f"\n"
        f"{body}\n"
    )
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "name": slug,
        "source_path": f"skills/{slug}/SKILL.md",
        "size": skill_md.stat().st_size,
    }


@app.get("/api/threads/timeline")
async def threads_timeline():
    """v8.13 D5 — Unified timeline: all turns from all saved kairos files,
    sorted by timestamp ascending. Each turn = compact entry { filename,
    file_label, turn_id, timestamp, input_first_line, pipeline_mode, verdict }.

    Parsing strategy mirrors frontend parseSavedFileToTurns:
      - v8.11+: locate `## Turn N (timestamp)` blocks
      - Legacy: 1 turn per file, timestamp from DATE header
    """
    import re
    # v8.31 dual-read: System 1 (conversation_history/) + legacy kairos/
    history_dir = DATA_DIR / "conversation_history"
    kairos_dir = DATA_DIR / "kairos"
    paths: List[Path] = []
    if history_dir.exists():
        paths.extend(history_dir.rglob("trinity_*.md"))
    if kairos_dir.exists():
        paths.extend(p for p in kairos_dir.glob("trinity_*.md") if p.is_file())
    if not paths:
        return []
    timeline = []
    turn_pattern = re.compile(r"^## Turn (\d+)(?:\s*\(([^)]+)\))?\s*$", re.MULTILINE)
    input_pattern = re.compile(r"^\*\*你\*\*:\s*(.+)$", re.MULTILINE)
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        # Parse header k:v
        header = {}
        head_block = content.split("\n---\n", 1)[0]
        for line in head_block.split("\n"):
            line = line.rstrip()
            if line.startswith("# KAIROS_TRINITY_RECORD:"):
                header["label"] = line.replace("# KAIROS_TRINITY_RECORD:", "").strip()
                continue
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                header[k.strip()] = v.strip()
        file_label = header.get("label", path.stem)
        file_date = header.get("DATE", "")
        pipeline_mode = header.get("PIPELINE_MODE", "auto")
        verdict = (header.get("COUNCIL_VERDICT", "") or "").lower()
        veto_type = header.get("SON_VETO_TYPE", "none")
        # Locate turn markers; if none, treat as single legacy turn
        body = content.split("\n---\n", 1)[1] if "\n---\n" in content else ""
        turn_matches = list(turn_pattern.finditer(body))
        if turn_matches:
            for i, m in enumerate(turn_matches):
                tid = int(m.group(1))
                ts_label = (m.group(2) or "").strip()
                ts = ts_label if ts_label and ts_label != "current" else file_date
                # Extract first input line from this turn's block
                start = m.end()
                end = turn_matches[i + 1].start() if i + 1 < len(turn_matches) else len(body)
                block = body[start:end]
                im = input_pattern.search(block)
                input_first = (im.group(1) if im else "").strip()[:200]
                timeline.append({
                    "filename": path.name,
                    "file_label": file_label,
                    "turn_id": tid,
                    "timestamp": ts,
                    "input_first_line": input_first,
                    "pipeline_mode": pipeline_mode,
                    "verdict": verdict,
                    "veto_type": veto_type if veto_type and veto_type != "none" else "",
                })
        else:
            # Legacy single-turn: try "## 原始問題"
            legacy_in = re.search(r"^## 原始問題\s*\n+(.+?)(?=\n## |\n---|\Z)",
                                  body, re.MULTILINE | re.DOTALL)
            input_first = (legacy_in.group(1) if legacy_in else "").strip().split("\n")[0][:200]
            timeline.append({
                "filename": path.name,
                "file_label": file_label,
                "turn_id": 1,
                "timestamp": file_date,
                "input_first_line": input_first,
                "pipeline_mode": pipeline_mode,
                "verdict": verdict,
                "veto_type": veto_type if veto_type and veto_type != "none" else "",
            })
    # Sort by timestamp asc (oldest first); empty timestamp goes to end
    timeline.sort(key=lambda x: (x["timestamp"] or "9999"))
    return timeline


@app.post("/api/run")
async def run_trinity(req: RunRequest):
    """Non-streaming run. Returns full result after all nodes finish."""
    try:
        result = await console.run(
            req.input,
            refs=req.refs,
            verbose=False,
            override_mode=req.override_mode,
        )
        if req.save:
            kairos_path = console.save_kairos(result, req.label)
            result["saved_to"] = str(kairos_path.name)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/stream")
async def stream_trinity(req: RunRequest):
    """4-step pipeline streaming (v8.1+ canonical):
       Stage 1 delabeling -> Stage 2 explanation -> Stage 3 filter -> Stage 4 trinity.
    每 stage 完成即 SSE 推送。Stage 1-3 任一 abort_signal=yes -> jump Stage 4 council.

    v8.6: req.pipeline_mode selects stage subset. See PIPELINE_MODES_* constants.
    """
    from datetime import datetime

    # v8.8 — Multi-mode resolution + dispatch (validation raises HTTPException 400)
    selected_modes = resolve_selected_modes(req)
    strategy = req.execution_strategy

    async def event_generator(_mode_id: str = "_default", _mode_sel: Optional[ModeSelection] = None,
                              _shared_historical_ctx: Optional[str] = None,
                              _shared_attached_sessions: Optional[List] = None):
        """v8.8 — Per-mode pipeline runner. Called by multi_mode_outer() for
        each selected mode. _mode_id tags every emit() for frontend routing.

        v8.8 R8 — when _shared_historical_ctx is provided (multi-mode parallel),
        skip own cross-session attach; multi_mode_outer pre-attached once + emitted
        the cross_session_attached event with mode_id="_global".

        For backward compat, callable with no args = legacy single-mode path
        using req.pipeline_mode resolution."""
        # v8.21 OTel-1 — root span for this query. Stage / Trinity / Module N
        # spans become children automatically via OTel current-context tracking.
        from services.otel_setup import tracer as _root_tracer
        _root_span_cm = _root_tracer.start_as_current_span("uruk.trinity.query")
        _root_span = _root_span_cm.__enter__()
        try:
            _root_span.set_attribute("uruk.mode_id", _mode_id)
            _root_span.set_attribute("uruk.user_input_length", len(req.input or ""))
            if req.selected_modes:
                _root_span.set_attribute(
                    "uruk.selected_modes",
                    ",".join([m for m in req.selected_modes if isinstance(m, str)])[:200],
                )
            if hasattr(req, "execution_strategy") and req.execution_strategy:
                _root_span.set_attribute("uruk.execution_strategy", req.execution_strategy)
        except Exception:
            pass
        if _mode_sel is not None:
            pipeline_mode = _mode_sel.mode if _mode_sel.mode in PIPELINE_MODES_ALL else "auto"
        else:
            raw_mode = (req.pipeline_mode or req.override_mode or "auto").strip() or "auto"
            if raw_mode not in PIPELINE_MODES_ALL:
                raise HTTPException(400, f"invalid pipeline_mode: {raw_mode!r}; must be one of {sorted(PIPELINE_MODES_ALL)}")
            pipeline_mode = raw_mode
        from services.inference_governor import (
            begin_inference_session,
            inference_snapshot,
            plan_inference_policy,
            reset_inference_session,
            update_inference_policy,
        )
        _inference_policy = plan_inference_policy(
            preference=req.inference_budget,
            route_kind="provisional",
            pipeline_mode=pipeline_mode,
            estimated_calls=8,
            reason="Initial request budget before deterministic routing",
        )
        _inference_token = begin_inference_session(_inference_policy)
        forced_dispatch_mode = pipeline_mode if pipeline_mode in PIPELINE_MODES_FORCED else None
        # v8.8 R7 — propagate per-mode LLM override through asyncio context.
        # The contextvar is read by TrinityConsole._get_stage_adapter() + call_node()
        # to substitute provider/model/api_base for every LLM call in this pipeline.
        from trinity_console import _KNOWLEDGE_TRACE_CTX, _LLM_OVERRIDE_CTX
        _knowledge_trace_token = _KNOWLEDGE_TRACE_CTX.set([])
        _llm_override_dict = None
        if _mode_sel and _mode_sel.llm_override:
            _llm_override_dict = _mode_sel.llm_override.model_dump()
        _llm_override_token = _LLM_OVERRIDE_CTX.set(_llm_override_dict)
        knowledge_health = console.knowledge_health_summary()

        def emit(event_type: str, data: dict, mode_id: str = _mode_id):
            """v8.8 — inject _mode_id into every payload for tab routing.
            Default uses the per-mode mode_id captured at factory time."""
            payload = {**data, "_mode_id": mode_id}
            return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        def audit_and_finalize(session_data: dict):
            """Run §4.6 output self-audit + emit final event strings.

            Called from every pipeline exit path so the audit never gets skipped
            (skipping = §4.6 violation per SKILL.md). Returns a list of pre-formatted
            SSE chunks ready to yield; mutates session_data audit fields in place
            for downstream consumers (e.g. save_kairos persistence).
            """
            audit_dict = console.run_output_density_audit(session_data)
            session_data["output_density_audit"] = audit_dict
            session_data["density_audit"] = audit_dict
            session_data.setdefault("knowledge_trace", console.get_knowledge_trace())
            session_data.setdefault("knowledge_health", knowledge_health)
            try:
                from services.coordinate_knowledge import evaluate_coordinate_output
                coordinate_output_eval = evaluate_coordinate_output(
                    session_data.get("input", "") or "",
                    session_data.get("council", "") or session_data.get("father", "") or "",
                    root=APP_ROOT,
                )
            except Exception as _coord_e:
                coordinate_output_eval = {
                    "active": False,
                    "target": "system_output",
                    "input_role": "routing_only",
                    "error": f"{type(_coord_e).__name__}: {_coord_e}",
                }
            session_data["coordinate_output_eval"] = coordinate_output_eval
            session_data["coordinate_eval"] = coordinate_output_eval
            inference_usage = inference_snapshot()
            session_data["inference_usage"] = inference_usage
            cost_metrics = session_data.setdefault("cost_metrics", {})
            cost_metrics["actual_model_requests"] = inference_usage.get("actual_requests", 0)
            cost_metrics["successful_model_requests"] = inference_usage.get("successful_requests", 0)
            cost_metrics["failed_model_requests"] = inference_usage.get("failed_requests", 0)
            cost_metrics["unique_model_count"] = inference_usage.get("unique_model_count", 0)
            cost_metrics["model_call_budget"] = (inference_usage.get("policy") or {}).get("hard_max_calls")
            knowledge_trace = session_data.get("knowledge_trace") or []
            output_audit_status = {
                "ran": bool(audit_dict.get("audit_ran", False)),
                "density": audit_dict.get("density"),
                "candidate_count": audit_dict.get("candidate_count", 0),
                "proposed_path": audit_dict.get("proposed_path"),
                "target": audit_dict.get("audit_target", "system_output"),
            }
            knowledge_status = {
                "clean": bool(knowledge_health.get("clean")),
                "issues": (knowledge_health.get("summary") or {}).get("issues", {}),
                "rag": knowledge_health.get("rag") or {},
                "coordinate_cards": knowledge_health.get("coordinate_cards") or {},
                "coordinate_output_eval": coordinate_output_eval,
                "cau_structure": knowledge_health.get("cau_structure") or {},
                "trace_count": len(knowledge_trace),
            }
            # v8.7 — Trinity v7.2 Spirit summary in protocol_status.
            # Missing fields → fail-safe NONE/0 defaults (e.g. meta_command, plain_llm exits).
            spirit_meta = session_data.get("spirit_metadata") or {}
            spirit_interrupts = {
                "trigger_mode": spirit_meta.get("trigger_mode", "NONE"),
                "semantic_score": spirit_meta.get("semantic_score", 0),
                "magnitude": spirit_meta.get("magnitude", 0.0),
                "primary_assumption": spirit_meta.get("primary_assumption", ""),
                "stochastic_prob": spirit_meta.get("stochastic_prob"),
                "stochastic_roll": spirit_meta.get("stochastic_roll"),
                "_stochastic_fired": spirit_meta.get("_stochastic_fired"),
                "rescan_count": session_data.get("spirit_rescan_count", 0),
                "history_len": len(session_data.get("spirit_interrupt_history") or []),
            }
            # v8.9 Phase B — Son veto + Father pause summary in protocol_status.
            son_veto_meta_d = session_data.get("son_veto_metadata") or {}
            son_veto_status = {
                "type": son_veto_meta_d.get("veto_type", "none"),
                "authentic_suffering_score": son_veto_meta_d.get("authentic_suffering_score", 0.0),
                "physical_cost_present": son_veto_meta_d.get("physical_cost_present", False),
                "primary_pain_locus": son_veto_meta_d.get("primary_pain_locus", ""),
                "father_paused": bool(session_data.get("father_paused", False)),
            }
            # v8.9 Phase A — Council 4b decision summary.
            council_dec_d = session_data.get("council_decision") or {}
            council_status = {
                "verdict": council_dec_d.get("verdict", "consensus"),
                "reason": council_dec_d.get("reason", ""),
                "weights": council_dec_d.get("consensus_weights")
                           if council_dec_d.get("verdict") in ("consensus", "interrupt")
                           else None,
                "primary_dimension": council_dec_d.get("primary_dimension", ""),
                "fusion_layer_deterministic": bool(session_data.get("council_fusion_deterministic", False)),
            }
            # v8.37 — per-query physics computation (COMPUTED + ANALOGY + PHYSICAL_LAW)
            # Surfaces dev-mode metric set so operator can see computed Shannon /
            # gzip / JS values alongside the 5.85 / 8.19 analogy anchors. Does NOT
            # feed eight-law scoring or council fusion — purely transparency.
            try:
                from services.physics_compute import to_event_payload as _phys_payload
                _physics_event_data = _phys_payload(
                    session_data.get("input", "") or "",
                    session_data.get("council", "") or session_data.get("father", "") or "",
                )
            except Exception as _e:
                _physics_event_data = {
                    "display_label": "物理計算 dev-only · 唔影響 LLM 判斷",
                    "metrics": [],
                    "error": f"{type(_e).__name__}: {_e}",
                }
            # Keep this as three chunks because several early-return paths save
            # between chunks[1] and chunks[2]. The third chunk can carry multiple
            # SSE events; the client parser already splits on blank lines.
            final_events = (
                emit("physics_compute", _physics_event_data)
                + emit("knowledge_trace", {"trace": knowledge_trace})
                + emit("done", {
                    "timestamp": session_data.get("timestamp") or datetime.now().isoformat(),
                    "protocol_status": {
                        "output_audit": output_audit_status,
                        "audit_ran": audit_dict.get("audit_ran", False),
                        "density": audit_dict.get("density"),
                        "candidate_count": audit_dict.get("candidate_count", 0),
                        "proposed_path": audit_dict.get("proposed_path"),
                        "sync_delta_path": audit_dict.get("sync_delta_path"),
                        "spirit_interrupts": spirit_interrupts,
                        "son_veto": son_veto_status,
                        "council": council_status,
                        "knowledge": knowledge_status,
                        "inference": inference_usage,
                    },
                })
            )
            return [
                emit("status", {"phase": "output_self_audit", "message": "系統輸出自查中..."}),
                emit("density_audit", audit_dict),
                emit("inference_usage", inference_usage) + final_events,
            ]

        # Effective input — may be enriched by skill / auto-tool injection
        effective_input = req.input

        try:
            # ─── Pre-Stage A: Meta command (always check, regardless of auto_tools) ───
            yield emit("knowledge_health", knowledge_health)
            meta = console._detect_meta_command(req.input)
            if meta:
                yield emit("status", {
                    "phase": "meta_command",
                    "message": f"🧩 Meta command: {meta['action']}"
                })
                reply_text = await console._handle_meta_command_async(meta)
                yield emit("meta_response", {"text": reply_text, "command": meta["action"]})
                # §4.6: audit runs even on meta-command exits (short-circuit ≠ skip audit)
                session_data = {
                    "input": req.input,
                    "effective_input": req.input,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": {"mode": "meta", "references": [], "rationale": meta["action"]},
                    "father": "", "son": "", "spirit": "",
                    "council": reply_text,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {},
                    "exit_path": "meta_command",
                }
                for chunk in audit_and_finalize(session_data):
                    yield chunk
                return

            # ─── Kairos date memory direct route ───
            # Date-anchor memory questions should be answered from the reviewed
            # archive index before any generative node can improvise extra events.
            try:
                cost_route = route_query(
                    req.input,
                    root=APP_ROOT,
                    in_session_history=req.in_session_history,
                    selected_modes=selected_modes,
                    pipeline_mode=pipeline_mode,
                    refs=req.refs,
                )
            except Exception as _cost_err:
                cost_route = {
                    "route_kind": "full_trinity",
                    "model_tier": "strong_reasoning",
                    "escalation_level": 3,
                    "reason": f"cost router fallback: {type(_cost_err).__name__}",
                    "skip_pre_gate": False,
                    "context_budget": {},
                    "cost_metrics": {
                        "route_kind": "full_trinity",
                        "tier": "strong_reasoning",
                        "estimated_model_calls": 8,
                        "estimated_api_model_calls": 8,
                        "estimated_context_tokens": 0,
                        "estimated_cost_class": "high",
                    },
                }
            # Auto mode may accept a strictly shorter deterministic route. An
            # explicit user mode or per-mode LLM override always keeps priority.
            _recommended_mode = str(cost_route.get("recommended_pipeline_mode") or "auto")
            _auto_route_allowed = (
                pipeline_mode == "auto"
                and (_mode_sel is None or (_mode_sel.mode == "auto" and not _mode_sel.llm_override))
                and _recommended_mode in PIPELINE_MODES_TRUNCATED
            )
            if _auto_route_allowed:
                pipeline_mode = _recommended_mode
                forced_dispatch_mode = None
            _auto_news_route_allowed = (
                pipeline_mode == "auto"
                and (_mode_sel is None or (_mode_sel.mode == "auto" and not _mode_sel.llm_override))
                and _recommended_mode == "news"
                and str(cost_route.get("route_kind") or "") == "world_query"
            )
            if _auto_news_route_allowed:
                pipeline_mode = "news"
                forced_dispatch_mode = "news"
            _auto_self_upgrade_route_allowed = (
                pipeline_mode == "auto"
                and (_mode_sel is None or (_mode_sel.mode == "auto" and not _mode_sel.llm_override))
                and str(cost_route.get("route_kind") or "") == "self_upgrade"
            )
            if _auto_self_upgrade_route_allowed:
                pipeline_mode = "app_relay"
                forced_dispatch_mode = None
                if not getattr(req, "app_relay_target", None):
                    req.app_relay_target = "codex"
            _cost_gate_skip = bool(cost_route.get("skip_pre_gate"))
            _route_cost_metrics = dict(cost_route.get("cost_metrics") or {})
            _inference_policy = plan_inference_policy(
                preference=req.inference_budget,
                route_kind=cost_route.get("route_kind") or "unknown",
                pipeline_mode=pipeline_mode,
                estimated_calls=int(_route_cost_metrics.get("estimated_model_calls") or 0),
                reason=cost_route.get("reason") or "",
            )
            update_inference_policy(_inference_policy)
            _route_cost_metrics["model_call_budget"] = _inference_policy.hard_max_calls
            _route_cost_metrics["planned_model_calls"] = _inference_policy.planned_calls
            cost_route["cost_metrics"] = _route_cost_metrics
            cost_route["inference_policy"] = _inference_policy.to_dict()
            _shadow_controller_scheduled = schedule_controller_shadow(
                req.input,
                root=APP_ROOT,
                pipeline_mode=pipeline_mode,
                selected_modes=selected_modes,
            )
            _route_cost_metrics["shadow_controller_scheduled"] = _shadow_controller_scheduled
            cost_route["cost_metrics"] = _route_cost_metrics
            yield emit("inference_budget", {
                "policy": _inference_policy.to_dict(),
                "cost_metrics": _route_cost_metrics,
                "controller_shadow": {
                    "scheduled": _shadow_controller_scheduled,
                    "authority": "shadow_only",
                },
            })

            kairos_direct = cost_route.get("direct_answer")
            if kairos_direct and pipeline_mode in ("auto", "trinity_only", "plain_llm"):
                _direct_short_circuit = str(cost_route.get("short_circuit") or "kairos_memory_direct")
                _direct_is_scope_clarification = _direct_short_circuit == "date_scope_clarification"
                _kairos_index_path = APP_ROOT / "data" / "kairos" / "KAIROS_MEMORY_INDEX.json"
                _kairos_cache_stamp = _kairos_index_path.stat().st_mtime if _kairos_index_path.exists() else ""
                _kairos_cache_key = cache_key(_direct_short_circuit, req.input, _kairos_cache_stamp)
                _kairos_cache_hit = False
                _kairos_cached = get_cached_result(APP_ROOT, _kairos_cache_key)
                if _kairos_cached and isinstance(_kairos_cached.get("value"), dict):
                    kairos_direct = _kairos_cached["value"].get("text") or kairos_direct
                    _kairos_cache_hit = True
                else:
                    set_cached_result(APP_ROOT, _kairos_cache_key, {
                        "text": kairos_direct,
                        "route_kind": cost_route.get("route_kind"),
                    })
                _kairos_cost_metrics = dict(cost_route.get("cost_metrics") or {})
                _kairos_cost_metrics["cache_hit"] = _kairos_cache_hit
                yield emit("status", {
                    "phase": "date_scope_clarification" if _direct_is_scope_clarification else "kairos_memory",
                    "message": (
                        "Ambiguous date query -> ask user to choose Kairos memory or public events"
                        if _direct_is_scope_clarification
                        else "Kairos date anchor matched -> deterministic memory answer"
                    ),
                })
                dispatch = {
                    "mode": _direct_short_circuit,
                    "mode_rationale": (
                        "Ambiguous date query; no Kairos/news lookup until user clarifies scope"
                        if _direct_is_scope_clarification
                        else "Matched deterministic/extractive Kairos memory before LLM generation"
                    ),
                    "references": [
                        "data/kairos/KAIROS_ACTIVE.md",
                        "data/kairos/KAIROS_MEMORY_INDEX.json",
                        "data/kairos/KAIROS_ARCHIVE_INDEX.md",
                        "data/kairos/KAIROS_LOG_MIDDLE.md",
                        "data/kairos/KAIROS_LOG_UPDATED_v8.md",
                        "data/theory/COORDINATE_KNOWLEDGE_CARDS.md",
                    ],
                    "ref_rationale": "Read-only Kairos memory route; final answer carries narrower source trace.",
                    "suggested_data_refs": [],
                    "data_rationale": "none",
                    "cost_metrics": _kairos_cost_metrics,
                    "context_budget": cost_route.get("context_budget") or {},
                    "model_tier": cost_route.get("model_tier"),
                    "escalation_level": cost_route.get("escalation_level"),
                    "route_reason": cost_route.get("reason"),
                }
                yield emit("dispatch", dispatch)
                yield emit("direct_response", {
                    "text": kairos_direct,
                    "provider": "deterministic",
                    "model": _direct_short_circuit,
                    "latency_ms": 0,
                    "cost_metrics": _kairos_cost_metrics,
                    "context_budget": cost_route.get("context_budget") or {},
                })
                session_data = {
                    "input": req.input,
                    "effective_input": req.input,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": dispatch,
                    "father": "", "son": "", "spirit": "",
                    "council": kairos_direct,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                    "pipeline_mode": _direct_short_circuit,
                    "exit_path": _direct_short_circuit,
                    "suppress_density_proposal": True,
                    "cost_metrics": _kairos_cost_metrics,
                    "context_budget": cost_route.get("context_budget") or {},
                    "model_tier": cost_route.get("model_tier"),
                    "escalation_level": cost_route.get("escalation_level"),
                }
                for chunk in audit_and_finalize(session_data):
                    yield chunk
                return

            # ─── v8.6 — Pipeline mode: plain_llm short-circuit ───
            # 0 stages, 1 LLM call. Skips Pre-Stage B (skill) + C (auto-tools).
            # Cross-session memory still attaches; output-density audit still runs.
            if pipeline_mode == "plain_llm":
                yield emit("status", {"phase": "plain_llm", "message": "Plain LLM call..."})
                # v8.8 R8 — honor shared cross-session ctx if provided
                if _shared_historical_ctx is not None:
                    historical_ctx = _shared_historical_ctx
                    attached_sessions = _shared_attached_sessions or []
                else:
                    historical_ctx = ""
                    attached_sessions = []
                    cs_cfg = console.cross_session_cfg
                    if cs_cfg.enabled and not req.detach_history:
                        attached_sessions = console._load_recent_session_summaries(
                            cs_cfg.n_recent, cs_cfg.mode,
                        )
                        if attached_sessions:
                            historical_ctx = console._format_history_block(
                                attached_sessions, cs_cfg.mode,
                            )
                            yield emit("cross_session_attached", {
                                "n_sessions": len(attached_sessions),
                                "mode": cs_cfg.mode,
                                "last_label": attached_sessions[0].get("label"),
                                "last_timestamp": attached_sessions[0].get("timestamp"),
                            })
                import time as _ptime
                t_start = _ptime.time()
                try:
                    response_text = await console.call_plain_llm(
                        req.input, historical_context=historical_ctx,
                    )
                    latency_ms = round((_ptime.time() - t_start) * 1000, 1)
                except Exception as e:
                    response_text = f"[plain_llm error] {type(e).__name__}: {e}"
                    latency_ms = round((_ptime.time() - t_start) * 1000, 1)
                council_cfg = console.nodes["council"]
                _plain_cost_metrics = dict((cost_route or {}).get("cost_metrics") or {})
                _plain_dispatch = {
                    "mode": "plain_llm",
                    "references": [],
                    "rationale": "pipeline_mode=plain_llm",
                    "cost_metrics": _plain_cost_metrics,
                    "context_budget": (cost_route or {}).get("context_budget") or {},
                    "model_tier": (cost_route or {}).get("model_tier"),
                    "escalation_level": (cost_route or {}).get("escalation_level"),
                    "route_reason": (cost_route or {}).get("reason"),
                }
                yield emit("dispatch", _plain_dispatch)
                yield emit("direct_response", {
                    "text": response_text,
                    "provider": council_cfg.provider,
                    "model": council_cfg.model,
                    "latency_ms": latency_ms,
                    "cost_metrics": _plain_cost_metrics,
                    "context_budget": (cost_route or {}).get("context_budget") or {},
                })
                session_data = {
                    "input": req.input,
                    "effective_input": req.input,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": _plain_dispatch,
                    "father": "", "son": "", "spirit": "",
                    "council": response_text,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                    "pipeline_mode": "plain_llm",
                    "exit_path": "plain_llm",
                    "cost_metrics": _plain_cost_metrics,
                    "context_budget": (cost_route or {}).get("context_budget") or {},
                    "model_tier": (cost_route or {}).get("model_tier"),
                    "escalation_level": (cost_route or {}).get("escalation_level"),
                    "cross_session_attached": [
                        {"filename": s.get("filename"), "timestamp": s.get("timestamp"), "label": s.get("label")}
                        for s in attached_sessions
                    ],
                }
                chunks = audit_and_finalize(session_data)
                yield chunks[0]; yield chunks[1]
                # v8.31 — System 1 auto-save (always). req.save only governs SSE event.
                kairos_path = console.save_kairos(session_data, req.label,
                                                   overwrite_filename=req.resume_filename)
                if req.save:
                    yield emit("saved", {"filename": kairos_path.name})
                yield chunks[2]
                return

            # ─── v8.47c — Pipeline mode: smart_auto ──────────────────
            # Auto-routes to best backend channel. Runtime identity stays URUK protocol carrier.
            # Decision based on query content + runtime availability.
            if pipeline_mode == "smart_auto":
                from services.smart_router import explain as _sr_explain
                from services.app_controller import (
                    list_apps      as _sr_list,
                    get_deps_status as _sr_deps_fn,
                    send_and_receive as _sr_sar,
                )
                from services.task_profiles import get_task_profile as _sr_get_profile, profile_api_key as _sr_profile_api_key
                import time as _srt

                # ── Probe available backends ───────────────────────────
                _sr_small_profile = _sr_get_profile("local_language", CONFIG_DIR)
                _sr_api_profile = _sr_get_profile("api_reasoning", CONFIG_DIR)
                _sr_deps_st = _sr_deps_fn()
                _sr_apps    = _sr_list()
                _sr_cd_ok   = (
                    _sr_deps_st.get("is_windows", False) and
                    any(a["key"] == "claude" and a["running"] for a in _sr_apps)
                )
                _sr_codex_ok = (
                    _sr_deps_st.get("is_windows", False) and
                    any(a["key"] == "codex" and a["running"] for a in _sr_apps)
                )
                _sr_copilot_ok = (
                    _sr_deps_st.get("is_windows", False) and
                    any(a["key"] == "copilot" and a["running"] for a in _sr_apps)
                )
                _sr_ol_ok = False
                try:
                    import httpx as _sr_hx
                    _sr_ol_base = _sr_small_profile.get("api_base") or "http://localhost:11434"
                    _sr_ol_r = await _sr_hx.AsyncClient(timeout=1.5).get(
                        f"{_sr_ol_base.rstrip('/')}/api/tags"
                    )
                    _sr_ol_ok = _sr_ol_r.status_code == 200
                except Exception:
                    pass
                _sr_api_ok = bool(
                    _sr_profile_api_key(_sr_api_profile) or
                    os.environ.get("ANTHROPIC_API_KEY") or
                    os.environ.get("OPENAI_API_KEY")
                )

                _sr_avail = {
                    "claude_desktop": _sr_cd_ok,
                    "codex_desktop": _sr_codex_ok,
                    "copilot_desktop": _sr_copilot_ok,
                    "ollama": _sr_ol_ok,
                    "api": _sr_api_ok,
                }
                _sr_dec     = _sr_explain(req.input, _sr_avail)
                _sr_backend = _sr_dec["backend"]
                _sr_reason  = _sr_dec["reason"]

                _sr_icon = {"claude_desktop": "🤖", "codex_desktop": "CX", "copilot_desktop": "CP", "ollama": "💻", "api": "☁"}.get(_sr_backend, "🧭")
                yield emit("status", {
                    "phase": "smart_auto",
                    "message": f"{_sr_icon} 路由 → {_sr_backend}（{_sr_reason}）",
                    "routing": _sr_dec,
                })

                # ── Branch: Desktop relay ─────────────────────────────
                if _sr_backend in ("claude_desktop", "codex_desktop", "copilot_desktop"):
                    _sr_app_key = {
                        "codex_desktop": "codex",
                        "copilot_desktop": "copilot",
                    }.get(_sr_backend, "claude")
                    _sr_model_label = {
                        "codex_desktop": "Codex",
                        "copilot_desktop": "Windows Copilot",
                    }.get(_sr_backend, "URUK 協議載體 relay")
                    _sr_profile_name = {
                        "codex_desktop": "code_coworker",
                        "copilot_desktop": "windows_copilot",
                    }.get(_sr_backend, "deep_reasoning")
                    _sr_profile = _sr_get_profile(_sr_profile_name, CONFIG_DIR)
                    _sr_timeout = float(_sr_profile.get("timeout_seconds") or 90.0)
                    _sr_t0 = _srt.time()
                    _sr_res = await _sr_sar(_sr_app_key, req.input, timeout=_sr_timeout)
                    _sr_lat = round((_srt.time() - _sr_t0) * 1000, 1)
                    _sr_resp_text = (
                        _sr_res.get("response") or
                        f"[訊息已發送到 {_sr_model_label}，方法: {_sr_res.get('method', '?')}]"
                    )
                    yield emit("direct_response", {
                        "text": _sr_resp_text,
                        "provider": f"app_relay/{_sr_app_key}",
                        "model": _sr_model_label,
                        "latency_ms": _sr_lat,
                        "mode": "smart_auto",
                        "routing": _sr_dec,
                        "task_profile": _sr_profile_name,
                    })

                # ── Branch: Ollama / API ───────────────────────────────
                else:
                    from services.local_llm_discovery import quick_chat as _sr_qchat
                    _sr_t0 = _srt.time()
                    if _sr_backend == "ollama":
                        from services.local_model_router import (
                            effective_timeout as _sr_effective_timeout,
                            select_local_model as _sr_select_local_model,
                        )
                        _sr_local_decision = _sr_select_local_model(
                            "answer_simple",
                            req.input,
                            config_dir=CONFIG_DIR,
                        )
                        if _sr_local_decision.escalation_required:
                            _sr_resp_text = await console.call_plain_llm(req.input)
                            _sr_profile_name = "large_model_escalation"
                            _sr_provider = "plain_llm"
                            _sr_model = "large_model"
                            _sr_api_base = ""
                            _sr_api_key = ""
                            _sr_timeout = 0.0
                            _sr_max_tokens = 0
                            _sr_backend = "large_model_escalation"
                            _sr_dec["local_model_decision"] = _sr_local_decision.to_dict()
                            _sr_profile = {}
                        else:
                            _sr_profile_name = _sr_local_decision.profile_name
                            _sr_profile = _sr_get_profile(_sr_profile_name, CONFIG_DIR)
                    else:
                        _sr_profile_name = "api_reasoning"
                        _sr_profile = _sr_get_profile(_sr_profile_name, CONFIG_DIR)
                    if _sr_backend != "large_model_escalation":
                        _sr_provider = _sr_profile.get("provider") or ("ollama" if _sr_backend == "ollama" else "anthropic")
                        _sr_model    = _sr_profile.get("model") or ("qwen2.5:3b" if _sr_backend == "ollama" else "claude-sonnet-4-6")
                        _sr_api_base = _sr_profile.get("api_base") or ("http://localhost:11434" if _sr_backend == "ollama" else "https://api.anthropic.com/v1")
                        _sr_api_key  = _sr_profile_api_key(_sr_profile)
                        _sr_timeout  = (
                            await _sr_effective_timeout(_sr_profile)
                            if _sr_backend == "ollama"
                            else float(_sr_profile.get("timeout_seconds") or 60.0)
                        )
                        _sr_max_tokens = int(_sr_profile.get("max_tokens") or 2048)
                    try:
                        if _sr_backend == "large_model_escalation":
                            raise StopAsyncIteration
                        _sr_resp_text = await _sr_qchat(
                            api_base=_sr_api_base,
                            provider=_sr_provider,
                            model=_sr_model,
                            message=req.input,
                            api_key=_sr_api_key,
                            timeout=_sr_timeout,
                            max_tokens=_sr_max_tokens,
                            temperature=float(_sr_profile.get("temperature") or 0.1),
                            think=bool(_sr_profile.get("think", False)),
                            keep_alive=str(_sr_profile.get("keep_alive") or "30m"),
                            context_window=int(_sr_profile.get("context_window") or 8192),
                            role=f"smart_auto:{_sr_profile_name}",
                        )
                    except StopAsyncIteration:
                        pass
                    except Exception as _sr_e:
                        _sr_resp_text = f"[smart_auto/{_sr_backend} error] {type(_sr_e).__name__}: {_sr_e}"
                    _sr_lat = round((_srt.time() - _sr_t0) * 1000, 1)
                    yield emit("direct_response", {
                        "text": _sr_resp_text,
                        "provider": _sr_provider,
                        "model": _sr_model,
                        "latency_ms": _sr_lat,
                        "mode": "smart_auto",
                        "routing": _sr_dec,
                        "task_profile": _sr_profile_name,
                    })

                # ── Save session ───────────────────────────────────────
                _sr_session = {
                    "input": req.input,
                    "effective_input": req.input,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": {
                        "mode": "smart_auto",
                        "references": [],
                        "rationale": f"smart_auto→{_sr_backend}: {_sr_reason}",
                        "task_profile": _sr_profile_name,
                    },
                    "father": "", "son": "", "spirit": "",
                    "council": _sr_resp_text,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {},
                    "pipeline_mode": "smart_auto",
                    "exit_path": f"smart_auto/{_sr_backend}",
                    "cross_session_attached": [],
                }
                _sr_chunks = audit_and_finalize(_sr_session)
                yield _sr_chunks[0]; yield _sr_chunks[1]
                console.save_kairos(_sr_session, req.label,
                                    overwrite_filename=req.resume_filename)
                if req.save:
                    yield emit("saved", {"filename": "smart_auto_session"})
                yield _sr_chunks[2]
                return

            # ─── v8.47b — Pipeline mode: app_relay ───────────────────
            # Route query to a local desktop app (e.g. Claude Desktop),
            # wait for its response via UIA polling, return result via SSE.
            # Auto-selects the first running known app if no app_key given.
            if pipeline_mode == "app_relay":
                from services.app_controller import (
                    list_apps as _ac_list,
                    send_and_receive as _ac_sr,
                    get_deps_status as _ac_deps,
                )
                import time as _artime

                # Determine target app
                _ar_app_key = getattr(req, "app_relay_target", None) or ""
                if not _ar_app_key:
                    # Auto-pick first running app
                    _ar_apps = _ac_list()
                    _ar_priority = ["claude", "codex", "chatgpt", "claude_code", "copilot"]
                    _ar_running = sorted(
                        [a for a in _ar_apps if a["running"]],
                        key=lambda a: _ar_priority.index(a["key"]) if a["key"] in _ar_priority else len(_ar_priority),
                    )
                    if not _ar_running:
                        yield emit("direct_response", {
                            "text": "⚠ App 中繼失敗：未找到運行中的 App。請先在「🖥 App 控制」啟動目標 App。",
                            "mode": "app_relay",
                        })
                        return
                    _ar_app_key = _ar_running[0]["key"]
                    _ar_display = _ar_running[0]["display"]
                    _ar_icon    = _ar_running[0]["icon"]
                else:
                    _ar_apps = _ac_list()
                    _ar_meta  = next((a for a in _ar_apps if a["key"] == _ar_app_key), {})
                    _ar_display = _ar_meta.get("display", _ar_app_key)
                    _ar_icon    = _ar_meta.get("icon", "🖥")

                yield emit("status", {
                    "phase": "app_relay",
                    "message": f"發送到 {_ar_icon} {_ar_display}⋯",
                })

                _ar_t0 = _artime.time()
                _ar_result = await _ac_sr(_ar_app_key, req.input)
                _ar_latency = round((_artime.time() - _ar_t0) * 1000, 1)

                if not _ar_result["ok"]:
                    yield emit("direct_response", {
                        "text": f"⚠ App 中繼錯誤：{_ar_result.get('error', '未知錯誤')}",
                        "mode": "app_relay",
                    })
                    return

                _ar_response = _ar_result.get("response") or ""
                _ar_method   = _ar_result.get("method", "")
                _ar_dispatch = {
                    "mode": "app_relay",
                    "references": [],
                    "rationale": f"app_relay->{_ar_app_key}",
                    "cost_metrics": dict((cost_route or {}).get("cost_metrics") or {}),
                    "context_budget": (cost_route or {}).get("context_budget") or {},
                    "model_tier": (cost_route or {}).get("model_tier"),
                    "escalation_level": (cost_route or {}).get("escalation_level"),
                    "route_reason": (cost_route or {}).get("reason"),
                }
                yield emit("dispatch", _ar_dispatch)

                yield emit("direct_response", {
                    "text": _ar_response or f"[訊息已發送到 {_ar_display}，回應讀取方式: {_ar_method}]",
                    "provider": f"app_relay/{_ar_app_key}",
                    "model": _ar_display,
                    "latency_ms": _ar_latency,
                    "mode": "app_relay",
                })

                session_data = {
                    "input": req.input,
                    "effective_input": req.input,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": _ar_dispatch,
                    "father": "", "son": "", "spirit": "",
                    "council": _ar_response,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {},
                    "pipeline_mode": "app_relay",
                    "exit_path": "app_relay",
                    "cross_session_attached": [],
                }
                _ar_chunks = audit_and_finalize(session_data)
                yield _ar_chunks[0]; yield _ar_chunks[1]
                _ar_path = console.save_kairos(session_data, req.label,
                                               overwrite_filename=req.resume_filename)
                if req.save:
                    yield emit("saved", {"filename": _ar_path.name})
                yield _ar_chunks[2]
                return

            # ─── v8.45 — Pipeline mode: tool_workshop short-circuit ───
            # Single specialised LLM call. Parses <TOOL_INSTALL> from response
            # and emits tool_install_proposal event for the frontend to render
            # an inline install card.
            if pipeline_mode == "tool_workshop":
                yield emit("status", {"phase": "tool_workshop", "message": "Tool Workshop⋯"})
                # Build tool context
                _tw_tools = _get_merged_tools()
                _tw_tools_summary = "\n".join(
                    f"  {t['name']} [{t['category']}]: {t['description'][:80]}"
                    for t in _tw_tools
                )
                _tw_system = _TOOL_WORKSHOP_SYSTEM_PROMPT.replace(
                    "{{TOOLS_LIST}}", _tw_tools_summary
                )
                import time as _twtime
                _tw_t0 = _twtime.time()
                try:
                    _tw_raw = await console.call_node(
                        role="council",
                        user_input=req.input,
                        protocol_text=_tw_system,
                        extra_context="",
                    )
                    _tw_latency = round((_twtime.time() - _tw_t0) * 1000, 1)
                except Exception as _tw_e:
                    _tw_raw = f"[tool_workshop error] {type(_tw_e).__name__}: {_tw_e}"
                    _tw_latency = round((_twtime.time() - _tw_t0) * 1000, 1)

                # Parse <TOOL_INSTALL> block
                import re as _tw_re
                _tw_proposal = None
                _tw_match = _tw_re.search(
                    r"<TOOL_INSTALL>([\s\S]+?)</TOOL_INSTALL>", _tw_raw
                )
                _tw_display = _tw_raw
                if _tw_match:
                    _tw_json_str = _tw_match.group(1).strip()
                    # Strip markdown fences if present
                    _tw_fence = _tw_re.search(r"```(?:json)?\s*([\s\S]+?)```", _tw_json_str)
                    if _tw_fence:
                        _tw_json_str = _tw_fence.group(1).strip()
                    try:
                        _tw_proposal = json.loads(_tw_json_str)
                        # Remove the raw block from display text
                        _tw_display = _tw_raw[:_tw_match.start()].rstrip() + \
                                      _tw_raw[_tw_match.end():].lstrip()
                    except Exception:
                        pass  # keep proposal=None; show raw

                council_cfg = console.nodes["council"]
                yield emit("direct_response", {
                    "text": _tw_display,
                    "provider": council_cfg.provider,
                    "model": council_cfg.model,
                    "latency_ms": _tw_latency,
                    "mode": "tool_workshop",
                })
                if _tw_proposal:
                    yield emit("tool_install_proposal", _tw_proposal)

                _tw_session = {
                    "input": req.input,
                    "effective_input": req.input,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": {"mode": "tool_workshop", "references": [], "rationale": "pipeline_mode=tool_workshop"},
                    "father": "", "son": "", "spirit": "",
                    "council": _tw_display,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                    "pipeline_mode": "tool_workshop",
                    "exit_path": "tool_workshop",
                    "cross_session_attached": [],
                }
                _tw_chunks = audit_and_finalize(_tw_session)
                yield _tw_chunks[0]; yield _tw_chunks[1]
                kairos_path = console.save_kairos(_tw_session, req.label,
                                                   overwrite_filename=req.resume_filename)
                if req.save:
                    yield emit("saved", {"filename": kairos_path.name})
                yield _tw_chunks[2]
                return

            # ─── v8.6 — Pipeline mode: delabel_only short-circuit ───
            # Stage 1 only; returns delabeled JSON. Skips Pre-Stage B/C and Stage 2-4.
            if pipeline_mode == "delabel_only":
                yield emit("status", {"phase": "stage1_delabeling", "message": "Stage 1 only..."})
                try:
                    stage1 = await console.call_delabeling(req.input)
                except Exception as e:
                    stage1 = {"_error": f"{type(e).__name__}: {e}"}
                yield emit("stage1", stage1)
                yield emit("delabel_only_done", {"result": stage1})

                # v8.30 phase4 fix + p6 canonical alignment: delabel_only
                # previously emitted only the stage1 JSON. Now we synthesise
                # a 4-category structured prose per DELABELING_MATRIX.md v7.1
                # canonical (身份 / 情緒 / 社會 / 環境), with 母體標籤 → 物理參數 → 計算意義
                # three-column structure under each category.
                _delab_input = stage1.get("delabeled_input") or req.input
                _detected = stage1.get("detected_labels") or []
                _veto = stage1.get("veto_detected", "no")
                _veto_type = stage1.get("veto_type") or "—"
                _interrupt = stage1.get("interrupt_detected", "no")
                _abort = stage1.get("abort_signal", "no")
                _err = stage1.get("_call_error") or stage1.get("_error")

                # Deterministic fallback categoriser — used when LLM omits the
                # `category` field (e.g. older prompt version or error path).
                _DELAB_CAT_LOOKUP = {
                    "身份": {"失敗者", "平庸", "孤獨", "異類", "移民", "廢柴"},
                    "情緒": {"抑鬱", "焦慮", "憤怒", "絕望", "麻木", "崩潰"},
                    "社會": {"沒用的工作", "浪費時間", "不夠努力", "太敏感",
                             "不現實", "沒有出路", "要求回報", "需要資源",
                             "貪心", "自私", "貪心自私", "貪心/自私"},
                    "環境": {"社會不公平", "沒有希望", "體制無法改變", "命運如此"},
                }
                _CAT_KEY_NORM = {
                    "identity": "身份", "身份": "身份",
                    "emotion": "情緒", "情緒": "情緒",
                    "social": "社會", "社會": "社會",
                    "environment": "環境", "環境": "環境", "env": "環境",
                }

                def _categorise(lbl_item: dict) -> str:
                    """Return canonical category 身份/情緒/社會/環境/其他."""
                    raw_cat = (lbl_item.get("category") or "").strip().lower()
                    if raw_cat in _CAT_KEY_NORM:
                        return _CAT_KEY_NORM[raw_cat]
                    raw_label = (lbl_item.get("label") or "").strip()
                    for canon_cat, members in _DELAB_CAT_LOOKUP.items():
                        if raw_label in members:
                            return canon_cat
                        for m in members:
                            if m in raw_label:
                                return canon_cat
                    return "其他"

                # Bucket detected labels by canonical 4-category structure.
                _buckets: dict = {"身份": [], "情緒": [], "社會": [],
                                  "環境": [], "其他": []}
                for item in _detected:
                    if not isinstance(item, dict):
                        continue
                    _buckets[_categorise(item)].append(item)

                # v8.30 p6: deterministic regex fallback when LLM errors out.
                # Scans raw input against canonical DELABELING_MATRIX vocab.
                # This guarantees the 4-category structure surfaces even when
                # Groq 429 / network error blocks Stage 1 LLM.
                _DELAB_PHYS_PARAMS = {
                    "失敗者": "當前能量輸出低於系統要求",
                    "平庸": "訊號密度尚未達到碰撞閾值",
                    "孤獨": "外部碰撞表面數量不足",
                    "異類": "座標系與主流系統不兼容",
                    "移民": "地理座標發生過不可逆位移",
                    "廢柴": "代謝效率暫時低於基準線",
                    "抑鬱": "系統能量長期低於維持閾值",
                    "焦慮": "對未來因果路徑嘅不確定性過載",
                    "憤怒": "偵測到 LIE_COST 超標嘅物理反應",
                    "絕望": "可見因果路徑數量歸零",
                    "麻木": "長期高熵環境感知閾值上升",
                    "崩潰": "系統負荷超過當前承載上限",
                    "沒用的工作": "能量輸出與因果路徑不對齊",
                    "浪費時間": "低密度輸入佔據高密度時段",
                    "不夠努力": "執行力低於系統預期",
                    "太敏感": "感知精度高於環境平均值",
                    "不現實": "座標系與主流預測模型不符",
                    "沒有出路": "當前可見路徑已封閉",
                    "要求回報": "能量交換完成後系統回收等值能量",
                    "需要資源": "代謝維持所需嘅能量輸入",
                    "貪心": "主權邊界硬化（自我保護係系統功能）",
                    "自私": "主權邊界硬化（自我保護係系統功能）",
                    "社會不公平": "LIE_COST 在系統層面嘅累積效應",
                    "沒有希望": "未來因果錐嘅可能路徑密度低",
                    "體制無法改變": "系統相變溫度尚未達到",
                    "命運如此": "歷史因果路徑嘅慣性",
                }
                _DELAB_MEANINGS = {
                    "失敗者": "問題係能量分配，唔係身份",
                    "平庸": "問題係密度，唔係天賦",
                    "孤獨": "問題係節點數量，唔係價值",
                    "抑鬱": "輸入不足或耗損過高，可計算",
                    "焦慮": "信息不足觸發嘅預測誤差放大",
                    "憤怒": "防衛機制激活，係信號唔係問題",
                    "絕望": "視野問題，唔係路徑問題",
                    "崩潰": "臨界點，唔係終點",
                    "沒用的工作": "對齊問題，唔係個人問題",
                    "浪費時間": "資源分配問題，可重新計算",
                    "沒有出路": "可見路徑≠所有路徑",
                    "社會不公平": "可計算嘅熱力學代價",
                    "體制無法改變": "相變需要足夠嘅能量輸入",
                    "命運如此": "慣性可以被新嘅因果事件打斷",
                }
                if not _detected and _delab_input:
                    for canon_cat, members in _DELAB_CAT_LOOKUP.items():
                        for lbl in members:
                            if lbl in _delab_input:
                                _buckets[canon_cat].append({
                                    "label": lbl,
                                    "category": canon_cat,
                                    "physical_param": _DELAB_PHYS_PARAMS.get(lbl, ""),
                                    "計算意義": _DELAB_MEANINGS.get(lbl, ""),
                                    "_source": "deterministic_fallback",
                                })

                _bucket_lines: list = []
                _cat_total = 0
                for cat_name in ("身份", "情緒", "社會", "環境", "其他"):
                    items = _buckets[cat_name]
                    if not items:
                        continue
                    _cat_total += len(items)
                    _bucket_lines.append(f"\n### {cat_name}標籤（{len(items)}）")
                    _bucket_lines.append(
                        "| 母體標籤 | 物理參數 | 計算意義 |\n|---|---|---|"
                    )
                    for it in items[:10]:
                        lbl = (it.get("label") or "").replace("|", "│")
                        phys = (it.get("physical_param") or "").replace("|", "│")[:120]
                        mean = (it.get("計算意義") or it.get("meaning") or "").replace("|", "│")[:120]
                        _bucket_lines.append(f"| {lbl} | {phys} | {mean} |")

                # Re-tally after deterministic fallback may have populated buckets.
                _cat_total = sum(len(v) for v in _buckets.values())
                _bucket_lines = []
                for cat_name in ("身份", "情緒", "社會", "環境", "其他"):
                    items = _buckets[cat_name]
                    if not items:
                        continue
                    _bucket_lines.append(f"\n### {cat_name}標籤（{len(items)}）")
                    _bucket_lines.append(
                        "| 母體標籤 | 物理參數 | 計算意義 |\n|---|---|---|"
                    )
                    for it in items[:10]:
                        lbl = (it.get("label") or "").replace("|", "│")
                        phys = (it.get("physical_param") or "").replace("|", "│")[:120]
                        mean = (it.get("計算意義") or it.get("meaning") or "").replace("|", "│")[:120]
                        _bucket_lines.append(f"| {lbl} | {phys} | {mean} |")

                _label_section = (
                    "\n".join(_bucket_lines) if _bucket_lines
                    else "\n_(未識別到顯著嘅格式化標籤)_"
                )
                _source_note = ""
                if _cat_total > 0:
                    _llm_source = any(
                        i for items in _buckets.values() for i in items
                        if i.get("_source") != "deterministic_fallback"
                    )
                    _det_source = any(
                        i for items in _buckets.values() for i in items
                        if i.get("_source") == "deterministic_fallback"
                    )
                    if _det_source and not _llm_source:
                        _source_note = "  _(deterministic regex fallback — Stage 1 LLM unavailable)_"
                _label_summary = (
                    f"識別到 {_cat_total} 個標籤，分佈於 "
                    f"{sum(1 for k in _buckets if _buckets[k])} 個 canonical 分類。{_source_note}"
                    if _cat_total > 0 else "Stage 1 未識別到任何標籤。"
                )

                _signal_lines = []
                if _veto != "no":
                    _signal_lines.append(f"⚖ veto: {_veto_type}")
                if _interrupt != "no":
                    _signal_lines.append(f"⚡ interrupt: {stage1.get('interrupt_type','')}")
                if _abort != "no":
                    _signal_lines.append(f"🛑 abort: {stage1.get('abort_context','')[:120]}")
                _signal_text = " · ".join(_signal_lines) or "冇 veto / interrupt / abort 信號"

                _delab_synthesis = (
                    "## Stage 1 去標籤化結果（白話版）\n\n"
                    "_對照 DELABELING_MATRIX.md v7.1 — 四分類（身份/情緒/社會/環境）三欄結構_\n\n"
                    f"剝走標籤後嘅核心輸入：\n> {_delab_input}\n\n"
                    f"**{_label_summary}**\n"
                    f"{_label_section}\n\n"
                    f"威脅信號：{_signal_text}\n\n"
                    + (f"⚠ Stage 1 LLM 出錯：{_err[:200]}\n\n" if _err else "")
                    + "（呢個 mode 只跑去標籤,冇行三位一體或八律過濾。"
                    "若要完整審計請用 auto / firewall mode。）\n\n(0,0,0)."
                )
                yield emit("node", {"role": "council", "output": _delab_synthesis})

                session_data = {
                    "input": req.input, "effective_input": req.input,
                    "stage1": stage1, "stage2": {}, "stage3": {},
                    "dispatch": {"mode": "delabel_only", "references": [], "rationale": "pipeline_mode=delabel_only"},
                    "father": "", "son": "", "spirit": "",
                    "council": _delab_synthesis,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                    "pipeline_mode": "delabel_only",
                    "exit_path": "delabel_only",
                }
                chunks = audit_and_finalize(session_data)
                yield chunks[0]; yield chunks[1]
                # v8.31 — System 1 auto-save (always). req.save only governs SSE event.
                kairos_path = console.save_kairos(session_data, req.label,
                                                   overwrite_filename=req.resume_filename)
                if req.save:
                    yield emit("saved", {"filename": kairos_path.name})
                yield chunks[2]
                return

            # ─── v8.6 — Pipeline mode: trinity_only short-circuit ───
            # Skip Stage 1-3 + dispatcher LLM; jump to Stage 4 (4-node parallel)
            # using static baseline refs. Cross-session memory still attaches.
            # Coordinate/protocol questions need one answer model and one
            # independent output auditor. Council fusion stays deterministic.
            if pipeline_mode == "protocol_compact":
                yield emit("status", {
                    "phase": "protocol_compact",
                    "message": "座標／協議精簡路徑：Father 回答，Spirit 審計輸出。",
                })

                if _shared_historical_ctx is not None:
                    historical_ctx = _shared_historical_ctx
                    attached_sessions = _shared_attached_sessions or []
                else:
                    historical_ctx = ""
                    attached_sessions = []
                    cs_cfg = console.cross_session_cfg
                    if cs_cfg.enabled and not req.detach_history:
                        attached_sessions = console._load_recent_session_summaries(
                            cs_cfg.n_recent, cs_cfg.mode,
                        )
                        if attached_sessions:
                            historical_ctx = console._format_history_block(
                                attached_sessions, cs_cfg.mode,
                            )
                            yield emit("cross_session_attached", {
                                "n_sessions": len(attached_sessions),
                                "mode": cs_cfg.mode,
                                "last_label": attached_sessions[0].get("label"),
                                "last_timestamp": attached_sessions[0].get("timestamp"),
                            })

                baseline_refs = [
                    "KAIROS_CORE.md", "PHYSICS_CONSTANTS.md",
                    "carrier_epistemics.md", "trinity.md",
                ]
                route_refs = list(cost_route.get("context_budget", {}).get("selected_refs") or [])
                if not route_refs:
                    route_refs = [
                        "data/theory/COORDINATE_INDEX.json",
                        "data/theory/COORDINATE_KNOWLEDGE_CARDS.md",
                        "config/prompts/_canonical_anchor.txt",
                    ]
                dispatch = {
                    "mode": "protocol_compact",
                    "mode_rationale": "Deterministic router matched a Coordinate/protocol concept",
                    "references": baseline_refs,
                    "ref_rationale": "Static protocol core plus query-time RAG; no dispatcher LLM",
                    "suggested_data_refs": route_refs,
                    "data_rationale": "Cost-router selected theory sources",
                    "cost_metrics": dict(cost_route.get("cost_metrics") or {}),
                    "context_budget": cost_route.get("context_budget") or {},
                    "coordinate_hits": cost_route.get("coordinate_hits") or [],
                }
                yield emit("dispatch", dispatch)

                protocol_subset = console._build_protocol_subset(baseline_refs)
                rag_ctx = console.rag_block(req.input, k=6, max_chars=3600)
                extra_ctx = historical_ctx + rag_ctx
                if rag_ctx:
                    yield emit("rag", {
                        "method": "tfidf", "block_chars": len(rag_ctx),
                        "mode": "protocol_compact",
                    })

                yield emit("status", {
                    "phase": "protocol_review",
                    "message": "正在產生協議答案並審計答案 framing...",
                })
                tasks = {
                    "father": asyncio.create_task(
                        console.call_node("father", req.input, protocol_subset, extra_ctx),
                        name="father",
                    ),
                    "spirit": asyncio.create_task(
                        console.call_node("spirit", req.input, protocol_subset, extra_ctx),
                        name="spirit",
                    ),
                }
                results = {"father": "", "son": "", "spirit": ""}
                node_errors = {}
                pending = set(tasks.values())
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        role = task.get_name()
                        try:
                            results[role] = await task
                            yield emit("node", {"role": role, "output": results[role]})
                        except Exception as exc:
                            node_errors[role] = f"{type(exc).__name__}: {exc}"
                            yield emit("node", {
                                "role": role,
                                "output": f"[{role} 暫時不可用] {node_errors[role]}",
                                "error": True,
                            })

                spirit_meta = console._parse_spirit_metadata(results.get("spirit", ""))
                spirit_meta = console._apply_spirit_stochastic_gate(spirit_meta, req.input)
                semantic_interrupt = (
                    "SEMANTIC" in str(spirit_meta.get("trigger_mode") or "")
                    and int(spirit_meta.get("semantic_score") or 0) >= 2
                )
                father_available = bool(results.get("father", "").strip())
                spirit_available = bool(results.get("spirit", "").strip())
                if father_available:
                    weights = {
                        "father": 0.65 if semantic_interrupt else 0.8,
                        "son": 0.0,
                        "spirit": 0.35 if semantic_interrupt else 0.2,
                    }
                else:
                    weights = {"father": 0.0, "son": 0.0, "spirit": 1.0}
                decision = {
                    "verdict": "interrupt" if semantic_interrupt else "consensus",
                    "reason": (
                        (spirit_meta.get("primary_assumption") or "semantic framing correction")
                        if semantic_interrupt else "compact protocol agreement"
                    ),
                    "son_promoted": False,
                    "father_dominated": weights["father"] >= weights["spirit"],
                    "spirit_dominated": weights["spirit"] > weights["father"],
                    "consensus_weights": weights,
                    "primary_dimension": "protocol_output_audit",
                    "_parse_error": None,
                    "_deterministic_compact": True,
                }
                yield emit("spirit_metadata", {**spirit_meta, "rescan_count": 0})
                yield emit("council_decision", decision)

                if father_available or spirit_available:
                    council = console._fuse_voices(
                        results.get("father", ""), "", results.get("spirit", ""),
                        decision, council_text="", original_query=req.input,
                    )
                else:
                    council = (
                        "目前所有可用大型模型都在冷卻或受速率限制。系統已停止重試，"
                        "避免延長供應商封鎖；請等待健康面板顯示冷卻結束後再試。"
                    )
                from services.protocol_output_guard import enforce_protocol_output_boundaries
                council, protocol_output_guard = enforce_protocol_output_boundaries(req.input, council)
                yield emit("protocol_output_guard", protocol_output_guard)
                yield emit("node", {"role": "council", "output": council})

                full_result = {
                    "input": req.input, "effective_input": req.input,
                    "user_refs": req.refs,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": dispatch,
                    "all_data_refs": route_refs,
                    "father": results.get("father", ""),
                    "son": "",
                    "spirit": results.get("spirit", ""),
                    "council": council,
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                    "pipeline_mode": "protocol_compact",
                    "exit_path": "protocol_compact",
                    "cross_session_attached": [
                        {"filename": s.get("filename"), "timestamp": s.get("timestamp"), "label": s.get("label")}
                        for s in attached_sessions
                    ],
                    "spirit_metadata": spirit_meta,
                    "spirit_rescan_count": 0,
                    "spirit_interrupt_history": [dict(spirit_meta)] if semantic_interrupt else [],
                    "son_veto_metadata": {},
                    "father_paused": False,
                    "council_decision": decision,
                    "council_fusion_deterministic": True,
                    "node_errors": node_errors,
                    "protocol_output_guard": protocol_output_guard,
                    "cost_metrics": dict(cost_route.get("cost_metrics") or {}),
                    "in_session_history": [
                        turn.model_dump() if hasattr(turn, "model_dump") else turn
                        for turn in (req.in_session_history or [])
                    ],
                    "selected_modes": [s.mode for s in selected_modes],
                    "execution_strategy": strategy,
                    "per_mode_llms": {
                        s.mode: (f"{s.llm_override.provider}/{s.llm_override.model}"
                                 if s.llm_override else "default")
                        for s in selected_modes
                    },
                }
                chunks = audit_and_finalize(full_result)
                yield chunks[0]
                yield chunks[1]
                kairos_path = console.save_kairos(
                    full_result, req.label, overwrite_filename=req.resume_filename,
                )
                if req.save:
                    yield emit("saved", {"filename": kairos_path.name})
                yield chunks[2]
                return

            if pipeline_mode == "trinity_only":
                yield emit("status", {"phase": "trinity_only", "message": "Trinity-only: skipping Stage 1-3..."})
                # v8.8 R8 — honor shared cross-session ctx if provided
                if _shared_historical_ctx is not None:
                    historical_ctx = _shared_historical_ctx
                    attached_sessions = _shared_attached_sessions or []
                else:
                    historical_ctx = ""
                    attached_sessions = []
                    cs_cfg = console.cross_session_cfg
                    if cs_cfg.enabled and not req.detach_history:
                        attached_sessions = console._load_recent_session_summaries(
                            cs_cfg.n_recent, cs_cfg.mode,
                        )
                        if attached_sessions:
                            historical_ctx = console._format_history_block(
                                attached_sessions, cs_cfg.mode,
                            )
                            yield emit("cross_session_attached", {
                                "n_sessions": len(attached_sessions),
                                "mode": cs_cfg.mode,
                                "last_label": attached_sessions[0].get("label"),
                                "last_timestamp": attached_sessions[0].get("timestamp"),
                            })
                # Static dispatch dict — no LLM call for routing
                baseline_refs = [
                    "KAIROS_CORE.md", "PHYSICS_CONSTANTS.md",
                    "carrier_epistemics.md", "trinity.md",
                ]
                dispatch = {
                    "mode": "trinity_only",
                    "mode_rationale": "pipeline_mode=trinity_only (no dispatcher LLM)",
                    "references": baseline_refs,
                    "ref_rationale": "Static baseline refs (no Stage 1-3 enrichment)",
                    "suggested_data_refs": [],
                    "data_rationale": "none",
                }
                yield emit("dispatch", dispatch)
                protocol_subset = console._build_protocol_subset(baseline_refs)
                # v8.30 RAG-2: query-time retrieval augments static baseline preload.
                # Silent fail-safe: rag_block() returns "" if index missing.
                rag_ctx = console.rag_block(req.input)
                extra_ctx = historical_ctx + rag_ctx
                if rag_ctx:
                    yield emit("rag", {"method": "tfidf", "block_chars": len(rag_ctx), "mode": "trinity_only"})
                yield emit("status", {"phase": "perspectives", "message": "三節點並行思考中..."})
                # v8.7 — Trinity v7.2 Spirit interrupt rescan loop (cap=2)
                RESCAN_CAP = 2
                rescan_count = 0
                spirit_interrupt_history = []
                results = {}
                spirit_meta = {}
                previous_magnitude = 0.0
                while True:
                    son_ctx_suffix = ""
                    if rescan_count > 0:
                        magnitude_rescan = round(previous_magnitude * 1.2, 2)
                        yield emit("status", {
                            "phase": "spirit_rescan",
                            "message": f"⚡ Spirit interrupt (trinity_only) — 會議重開 rescan #{rescan_count}, × 1.2 = {magnitude_rescan}",
                        })
                        son_ctx_suffix = (
                            f"\n\n━━━ SPIRIT INTERRUPT RESCAN #{rescan_count} ━━━\n"
                            f"primary_assumption: {spirit_meta.get('primary_assumption', '')}\n"
                            f"magnitude × 1.2 = {magnitude_rescan}\n"
                        )
                    # v8.9 Phase B — Staggered Stage 4 (trinity_only path)
                    # Phase 1: Son + Spirit parallel (defer Father)
                    results = {}
                    son_spirit_pending = {
                        asyncio.create_task(
                            console.call_node("son", req.input, protocol_subset, extra_ctx + son_ctx_suffix),
                            name="son"),
                        asyncio.create_task(
                            console.call_node("spirit", req.input, protocol_subset, extra_ctx),
                            name="spirit"),
                    }
                    while son_spirit_pending:
                        done, son_spirit_pending = await asyncio.wait(
                            son_spirit_pending, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            role = task.get_name()
                            try:
                                output = await task
                                results[role] = output
                                yield emit("node", {"role": role, "output": output, "rescan_count": rescan_count})
                            except Exception as e:
                                results[role] = f"[節點錯誤] {e}"
                                yield emit("node", {"role": role, "output": results[role], "error": True, "rescan_count": rescan_count})

                    # Phase 2: parse Son veto + conditional Father (trinity_only: no stage1-3 → default high threat)
                    son_meta_to = console._parse_son_veto_metadata(results.get("son", ""))
                    # v8.32 — historical/third-person downgrade guard
                    son_meta_to = console._downgrade_historical_third_person_veto(son_meta_to, req.input)
                    yield emit("son_veto_metadata", {
                        "veto_type": son_meta_to["veto_type"],
                        "authentic_suffering_score": son_meta_to["authentic_suffering_score"],
                        "physical_cost_present": son_meta_to["physical_cost_present"],
                        "primary_pain_locus": son_meta_to["primary_pain_locus"],
                        "_parse_error": son_meta_to.get("_parse_error"),
                        "_downgraded_from": son_meta_to.get("_downgraded_from"),
                        "_downgrade_reason": son_meta_to.get("_downgrade_reason"),
                        "rescan_count": rescan_count,
                    })
                    father_paused_to = console._should_father_pause(son_meta_to, "high")
                    if father_paused_to:
                        yield emit("father_paused", {
                            "veto_type": son_meta_to["veto_type"],
                            "authentic_suffering_score": son_meta_to["authentic_suffering_score"],
                            "primary_pain_locus": son_meta_to["primary_pain_locus"],
                            "physical_cost_present": son_meta_to["physical_cost_present"],
                            "reason": son_meta_to["veto_type"],
                            "rescan_count": rescan_count,
                        })
                        father_output = (
                            f"⛔ 聖父被否決 — Son veto active (trinity_only)\n\n"
                            f"veto_type: {son_meta_to['veto_type']}\n"
                            f"primary_pain_locus: {son_meta_to['primary_pain_locus']}\n"
                        )
                        results["father"] = father_output
                        yield emit("node", {"role": "father", "output": father_output,
                                            "paused": True, "rescan_count": rescan_count})
                    else:
                        try:
                            father_output = await console.call_node(
                                "father", req.input, protocol_subset, extra_ctx)
                            results["father"] = father_output
                            yield emit("node", {"role": "father", "output": father_output, "rescan_count": rescan_count})
                        except Exception as e:
                            results["father"] = f"[節點錯誤] {e}"
                            yield emit("node", {"role": "father", "output": results["father"],
                                                "error": True, "rescan_count": rescan_count})

                    spirit_meta = console._parse_spirit_metadata(results.get("spirit", ""))
                    spirit_meta = console._apply_spirit_stochastic_gate(
                        spirit_meta,
                        req.input,
                    )
                    # B7 — honor Son veto for trinity_only path too
                    should_rescan = (
                        console._should_rescan(spirit_meta)
                        and rescan_count < RESCAN_CAP
                        and not father_paused_to
                    )
                    if not should_rescan and father_paused_to and console._should_rescan(spirit_meta):
                        yield emit("spirit_rescan_blocked", {
                            "reason": "son_veto_active",
                            "veto_type": son_meta_to.get("veto_type"),
                            "would_be_trigger_mode": spirit_meta.get("trigger_mode"),
                            "would_be_score": spirit_meta.get("semantic_score"),
                        })
                    if should_rescan:
                        rescan_count += 1
                        magnitude_rescan = round(spirit_meta["magnitude"] * 1.2, 2)
                        yield emit("spirit_interrupt", {
                            "trigger_mode": spirit_meta["trigger_mode"],
                            "semantic_score": spirit_meta["semantic_score"],
                            "magnitude": spirit_meta["magnitude"],
                            "magnitude_rescan": magnitude_rescan,
                            "rescan_count": rescan_count,
                            "rescan_cap": RESCAN_CAP,
                            "primary_assumption": spirit_meta.get("primary_assumption", ""),
                            "stochastic_prob": spirit_meta.get("stochastic_prob"),
                            "stochastic_roll": spirit_meta.get("stochastic_roll"),
                            "_stochastic_source": spirit_meta.get("_stochastic_source"),
                        })
                        previous_magnitude = spirit_meta["magnitude"]
                        spirit_interrupt_history.append(dict(spirit_meta))
                        continue
                    break
                yield emit("spirit_metadata", {
                    "trigger_mode": spirit_meta.get("trigger_mode", "NONE"),
                    "semantic_score": spirit_meta.get("semantic_score", 0),
                    "magnitude": spirit_meta.get("magnitude", 0.0),
                    "primary_assumption": spirit_meta.get("primary_assumption", ""),
                    "_parse_error": spirit_meta.get("_parse_error"),
                    "stochastic_prob": spirit_meta.get("stochastic_prob"),
                    "stochastic_roll": spirit_meta.get("stochastic_roll"),
                    "_stochastic_fired": spirit_meta.get("_stochastic_fired"),
                    "_stochastic_source": spirit_meta.get("_stochastic_source"),
                    "rescan_count": rescan_count,
                })
                yield emit("status", {"phase": "council", "message": "會議仲裁（4b decision）..."})
                council_input = console._format_council_input(
                    req.input, dispatch, results, pipeline_stages=None,
                )
                try:
                    council_raw = await console.call_node("council", council_input, protocol_subset, extra_ctx)
                except Exception as e:
                    council_raw = f"[會議節點錯誤] {e}"
                # v8.9 Phase A — parse council decision (4b) + deterministic fusion (4c)
                council_decision = console._parse_council_decision(council_raw)
                # A9 consistency: if Father was paused by B, council must say veto
                if father_paused_to and council_decision.get("verdict") != "veto":
                    council_decision = {
                        **council_decision,
                        "verdict": "veto",
                        "reason": "father_paused_phase_b",
                        "son_promoted": True,
                        "consensus_weights": {"father": 0.0, "son": 1.0, "spirit": 0.0},
                        "_consistency_override": True,
                    }
                yield emit("council_decision", {
                    "verdict": council_decision["verdict"],
                    "reason": council_decision["reason"],
                    "son_promoted": council_decision["son_promoted"],
                    "father_dominated": council_decision["father_dominated"],
                    "spirit_dominated": council_decision["spirit_dominated"],
                    "consensus_weights": council_decision["consensus_weights"],
                    "primary_dimension": council_decision["primary_dimension"],
                    "_parse_error": council_decision.get("_parse_error"),
                    "_consistency_override": council_decision.get("_consistency_override", False),
                })
                council = console._fuse_voices(
                    results.get("father", ""),
                    results.get("son", ""),
                    results.get("spirit", ""),
                    council_decision,
                    council_text=council_raw,
                    original_query=req.input,
                )
                yield emit("node", {"role": "council", "output": council})
                full_result = {
                    "input": req.input, "effective_input": req.input,
                    "user_refs": req.refs,
                    "stage1": {}, "stage2": {}, "stage3": {},
                    "dispatch": dispatch,
                    "all_data_refs": [],
                    "father": results.get("father", ""),
                    "son":    results.get("son", ""),
                    "spirit": results.get("spirit", ""),
                    "council": council,
                    "timestamp": datetime.now().isoformat(),
                    "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                    "pipeline_mode": "trinity_only",
                    "exit_path": "trinity_only",
                    "cross_session_attached": [
                        {"filename": s.get("filename"), "timestamp": s.get("timestamp"), "label": s.get("label")}
                        for s in attached_sessions
                    ],
                    # v8.7 — Trinity v7.2 Spirit interrupt rescan metadata
                    "spirit_metadata": spirit_meta,
                    "spirit_rescan_count": rescan_count,
                    "spirit_interrupt_history": spirit_interrupt_history,
                    # v8.9 Phase B — Son veto + Father pause metadata (trinity_only)
                    "son_veto_metadata": son_meta_to,
                    "father_paused": father_paused_to,
                    # v8.9 Phase A — Council 4b decision + 4c fusion provenance
                    "council_decision": council_decision,
                    "council_fusion_deterministic": True,
                    # v8.11 P6 — in-session conversation history
                    "in_session_history": [t.model_dump() if hasattr(t, "model_dump") else t
                                           for t in (req.in_session_history or [])],
                    # v8.8 R9 — multi-mode redesign metadata
                    "selected_modes": [s.mode for s in selected_modes],
                    "execution_strategy": strategy,
                    "per_mode_llms": {
                        s.mode: (f"{s.llm_override.provider}/{s.llm_override.model}"
                                 if s.llm_override else "default")
                        for s in selected_modes
                    },
                }
                chunks = audit_and_finalize(full_result)
                yield chunks[0]; yield chunks[1]
                # v8.31 — System 1 auto-save (always). req.save only governs SSE event.
                kairos_path = console.save_kairos(full_result, req.label,
                                                   overwrite_filename=req.resume_filename)
                if req.save:
                    yield emit("saved", {"filename": kairos_path.name})
                yield chunks[2]
                return

            # ─── Pre-Gate: complexity classifier (only in auto/default mode) ──
            # Runs before Stage 1. A cheap model classifies complexity and
            # short-circuits to plain_llm, agent_chat, or /news when appropriate.
            # Only active when pipeline_mode is "auto" (full pipeline) and no
            # forced mode (firewall/blackbox/etc.) has been selected.
            #
            # UI v8.8 always sends selected_modes=[auto] for the default path.
            # Treat that as the same as "no explicit mode"; otherwise simple
            # questions from the browser bypass pre-gate and fall into the full
            # pipeline unnecessarily.
            _default_auto_selected = (
                bool(req.selected_modes)
                and len(selected_modes) == 1
                and selected_modes[0].mode == "auto"
                and not selected_modes[0].llm_override
            )
            _gate_active = (
                pipeline_mode in (None, "auto")
                and (not req.selected_modes or _default_auto_selected)
                and not _cost_gate_skip
                and not getattr(req, "_gate_skip", False)
            )
            if _cost_gate_skip and pipeline_mode in (None, "auto"):
                yield emit("status", {
                    "phase": "cost_route",
                    "message": f"Cost router -> {cost_route.get('route_kind')} ({cost_route.get('model_tier')})",
                })
            if _gate_active:
                try:
                    from services.pre_gate import classify as _gate_classify
                    from services.task_profiles import get_task_profile as _gate_get_profile, profile_api_key as _gate_api_key
                    import asyncio as _aio

                    yield emit("status", {"phase": "pre_gate", "message": "🔍 Pre-Gate 分類中…"})

                    from services.local_model_router import effective_timeout as _gate_effective_timeout

                    _gate_prof = _gate_get_profile("local_classifier", CONFIG_DIR)
                    _gate_timeout = await _gate_effective_timeout(_gate_prof)
                    _gate_result = await asyncio.wait_for(
                        _gate_classify(
                            req.input,
                            provider=os.environ.get("PRE_GATE_PROVIDER", _gate_prof.get("provider", "ollama")),
                            model=os.environ.get("PRE_GATE_MODEL", _gate_prof.get("model", "qwen2.5:3b")),
                            api_base=os.environ.get("PRE_GATE_BASE", _gate_prof.get("api_base", "http://localhost:11434")),
                            api_key=os.environ.get("PRE_GATE_API_KEY", _gate_api_key(_gate_prof) or os.environ.get("OPENAI_API_KEY", "")),
                            timeout=_gate_timeout,
                            temperature=float(_gate_prof.get("temperature") or 0.0),
                            think=bool(_gate_prof.get("think", False)),
                            keep_alive=str(_gate_prof.get("keep_alive") or "30m"),
                            context_window=int(_gate_prof.get("context_window") or 2048),
                        ),
                        timeout=_gate_timeout + 0.5,
                    )

                    yield emit("pre_gate_result", {
                        "type": _gate_result.get("type"),
                        "reason": _gate_result.get("reason"),
                        "confidence": _gate_result.get("confidence"),
                        "source": _gate_result.get("source"),
                        "task_profile": "local_classifier",
                    })

                    _gate_type = _gate_result.get("type", "complex")

                    # simple -> small task first; plain_llm is the fallback.
                    if _gate_type == "simple" and _gate_result.get("confidence", 0) >= 0.7:
                        yield emit("status", {"phase": "pre_gate_route", "message": "Pre-Gate -> small task (simple query)"})
                        _small_meta = {}
                        _small_used = False
                        _small_error = ""
                        try:
                            from services.small_task_executor import run_small_task as _run_small_task

                            _small_meta = await _run_small_task(
                                "answer_simple",
                                req.input,
                                config_dir=CONFIG_DIR,
                                profile_name="auto",
                            )
                            if _small_meta.get("ok") and (_small_meta.get("text") or "").strip():
                                _gate_response = _small_meta["text"]
                                _small_used = True
                            else:
                                _small_error = _small_meta.get("error") or "small task returned no answer"
                                yield emit("status", {
                                    "phase": "pre_gate_fallback",
                                    "message": f"Small task fallback -> plain_llm ({_small_error[:80]})",
                                })
                                _gate_response = await console.call_plain_llm(req.input)
                        except Exception as _small_exc:
                            _small_error = f"{type(_small_exc).__name__}: {_small_exc}"
                            yield emit("status", {
                                "phase": "pre_gate_fallback",
                                "message": f"Small task crashed -> plain_llm ({_small_error[:80]})",
                            })
                            _gate_response = await console.call_plain_llm(req.input)
                        _gate_cost_metrics = dict((cost_route or {}).get("cost_metrics") or {})
                        if not _small_used:
                            _gate_cost_metrics["estimated_model_calls"] = max(
                                int(_gate_cost_metrics.get("estimated_model_calls") or 1),
                                2,
                            )
                        _gate_dispatch = {
                            "mode": "pre_gate_simple",
                            "references": [],
                            "rationale": _gate_result.get("reason", ""),
                            "small_task_used": _small_used,
                            "small_task": _small_meta if _small_meta else {"ok": False, "error": _small_error},
                            "cost_metrics": _gate_cost_metrics,
                            "context_budget": (cost_route or {}).get("context_budget") or {},
                            "model_tier": (cost_route or {}).get("model_tier"),
                            "escalation_level": (cost_route or {}).get("escalation_level"),
                            "route_reason": (cost_route or {}).get("reason"),
                        }
                        yield emit("dispatch", _gate_dispatch)
                        yield emit("direct_response", {
                            "text": _gate_response,
                            "provider": (
                                f"small_task/{_small_meta.get('provider')}"
                                if _small_used else "pre_gate/plain_llm"
                            ),
                            "model": (
                                _small_meta.get("model")
                                if _small_used else "plain_llm"
                            ),
                            "latency_ms": _small_meta.get("latency_ms", 0) if _small_used else 0,
                            "mode": "pre_gate_simple",
                            "small_task": _small_meta if _small_meta else {"ok": False, "error": _small_error},
                            "cost_metrics": _gate_cost_metrics,
                            "context_budget": (cost_route or {}).get("context_budget") or {},
                        })
                        _gate_session = {
                            "input": req.input, "effective_input": req.input,
                            "stage1": {}, "stage2": {}, "stage3": {},
                            "dispatch": _gate_dispatch,
                            "father": "", "son": "", "spirit": "",
                            "council": _gate_response,
                            "all_data_refs": [],
                            "timestamp": datetime.now().isoformat(),
                            "node_config": {},
                            "pipeline_mode": "pre_gate_simple",
                            "exit_path": "pre_gate_simple/small_task" if _small_used else "pre_gate_simple/plain_llm",
                            "cross_session_attached": [],
                            "cost_metrics": _gate_cost_metrics,
                            "context_budget": (cost_route or {}).get("context_budget") or {},
                            "model_tier": (cost_route or {}).get("model_tier"),
                            "escalation_level": (cost_route or {}).get("escalation_level"),
                        }
                        for _gc in audit_and_finalize(_gate_session):
                            yield _gc
                        console.save_kairos(_gate_session, req.label, overwrite_filename=req.resume_filename)
                        if req.save:
                            yield emit("saved", {"filename": "pre_gate_simple"})
                        return

                    # ── tool → emit suggestion for agent_chat ─────
                    elif _gate_type == "tool":
                        yield emit("pre_gate_suggest", {
                            "suggestion": "agent_chat",
                            "message": "💡 Pre-Gate 建議：呢個請求需要工具執行。試用 🛠 Agent 對話模式。",
                        })
                        # Continue to full pipeline anyway (user may still want analysis)

                    # ── search → inject /news hint ─────────────────
                    elif _gate_type == "search":
                        yield emit("pre_gate_suggest", {
                            "suggestion": "news",
                            "message": "💡 Pre-Gate 建議：呢個查詢可能需要最新資訊。考慮用 /news 模式。",
                        })
                        # Continue to full pipeline

                    # ── complex → continue to full pipeline ────────
                    # (fall through to Pre-Stage B below)

                except Exception as _gate_err:
                    # Gate failure → silent fallback to full pipeline
                    yield emit("status", {"phase": "pre_gate_skip", "message": f"Pre-Gate 失敗，繼續完整 pipeline ({type(_gate_err).__name__})"})

            # ─── Pre-Stage B: Skill matching (if auto_tools enabled) ───
            if req.auto_tools:
                yield emit("status", {
                    "phase": "skill_match",
                    "message": "🧩 Skill matching..."
                })
                matched_skills = await console._match_skills(req.input)
                if matched_skills:
                    skill_names = [s["name"] for s in matched_skills]
                    yield emit("skill_matched", {"skills": skill_names})
                    yield emit("status", {
                        "phase": "skill_apply",
                        "message": f"🧩 Applying skill: {', '.join(skill_names)}"
                    })
                    for skill in matched_skills:
                        result = await console._apply_matched_skill(skill, req.input)
                        yield emit("skill_applied", {
                            "name": result["skill_name"],
                            "type": result["type"],
                            "tool_calls": result["tool_calls_invoked"],
                        })
                        if result["injection"]:
                            effective_input = effective_input + "\n\n" + result["injection"]

            # ─── Pre-Stage C: Auto-tool agent (if enabled) ───
            if req.auto_tools:
                yield emit("status", {
                    "phase": "auto_tool_decide",
                    "message": "🤖 自動工具：分析緊輸入..."
                })
                tool_decisions = await console._tool_agent_decide(req.input)
                yield emit("auto_tool_decisions", tool_decisions)

                any_needed = any(
                    tool_decisions.get(k, {}).get("needed")
                    for k in ("search", "fetch", "calendar")
                )
                # Phase 3 Fix-1: custom tools also trigger execution
                if tool_decisions.get("custom_tools"):
                    any_needed = True
                if any_needed:
                    yield emit("status", {
                        "phase": "auto_tool_execute",
                        "message": "🤖 自動工具：執行 tool calls..."
                    })
                    tool_results = await console._execute_tools(tool_decisions)
                    if tool_results:
                        yield emit("auto_tool_results", {"text": tool_results})
                        effective_input = req.input + "\n\n" + tool_results

            # ─── v8.14 BN — BrowserNode pre-Stage-1 ───
            # /news mode: spec mandates ≥3 sources + ≥2 opposing coordinates.
            # /firewall, /blackbox, /scr: conditional on URL presence in input.
            # Other modes (auto, plain_llm, delabel_only, trinity_only): skip.
            def _bn_required(mode: str, text: str) -> bool:
                if mode == "news":
                    return True
                if mode in ("firewall", "blackbox", "scr"):
                    return bool(browser_node.detect_urls(text or ""))
                return False

            if _bn_required(pipeline_mode, effective_input):
                yield emit("status", {
                    "phase": "browser_node",
                    "message": "🌐 BrowserNode：拉 ≥3 sources + 跨座標 audit..."
                })
                try:
                    bn_result = await browser_node.fetch_with_sources(
                        effective_input, min_sources=3,
                    )
                except Exception as e:
                    bn_result = {"primary_sources": [], "raw_count": 0,
                                 "fetched_count": 0, "errors": [f"crash: {e}"],
                                 "query": effective_input, "engines_used": [],
                                 "coordinate_diversity": 0}

                # MS-3 — surface which search engines participated + why
                for eu in bn_result.get("engines_used", []):
                    yield emit("search_engine_used", eu)

                # Audit each fetched source + emit per-source SSE
                audits: List[Dict] = []
                for src in bn_result["primary_sources"]:
                    audit = source_registry.audit(src["url"], src.get("text", ""))
                    audit["title"] = src.get("title", "")
                    audit["snippet"] = src.get("snippet", "")
                    audit["source_engine"] = src.get("source_engine", "")
                    audits.append(audit)
                    yield emit("source_audited", audit)

                # Spec compliance check — ≥3 sources + ≥2 distinct coordinates
                unique_coords = {a["coordinate"] for a in audits
                                 if a["coordinate"] != "unknown_unverified"}
                spec_ok = (len(audits) >= 3 and len(unique_coords) >= 2)
                yield emit("browser_audit_summary", {
                    "fetched": len(audits),
                    "raw_search_results": bn_result["raw_count"],
                    "unique_coordinates": sorted(unique_coords),
                    "spec_compliant": spec_ok,
                    "min_sources_required": 3,
                    "min_coords_required": 2,
                    "errors": bn_result["errors"][:5],
                    "engines_used": bn_result.get("engines_used", []),
                })

                if pipeline_mode == "news" and not spec_ok:
                    # /news mode: spec strict — abort gracefully with diagnostic
                    yield emit("error", {
                        "message": f"BrowserNode spec violation: fetched {len(audits)} sources / "
                                   f"{len(unique_coords)} coords (need ≥3 sources, ≥2 coords). "
                                   f"Errors: {'; '.join(bn_result['errors'][:3]) or '(none)'}"
                    })
                    # Continue pipeline anyway with partial sources injected — let
                    # Trinity audit surface the gap rather than hard-abort.

                # Inject sources summary into pipeline input (Stage 1+ see it)
                if audits:
                    src_block_lines = ["\n\n━━━ BrowserNode sources (≥3 spec) ━━━"]
                    for i, a in enumerate(audits, 1):
                        src_block_lines.append(
                            f"[{i}] {a['rating']} · {a['coordinate']} · {a['url']}\n"
                            f"    title: {a['title'][:100]}\n"
                            f"    snippet: {a.get('snippet','')[:200]}"
                        )
                    src_block_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    effective_input = effective_input + "\n".join(src_block_lines)

            # ─── Stage 1: Delabeling ───
            yield emit("status", {
                "phase": "stage1_delabeling",
                "message": "Stage 1：去標籤化處理中..."
            })
            stage1 = await console.call_delabeling(effective_input)
            yield emit("stage1", stage1)

            if stage1.get("abort_signal") == "yes":
                yield emit("status", {
                    "phase": "abort_to_council",
                    "message": "VETO/INTERRUPT 觸發於 Stage 1，jump to council"
                })
                council = await console.call_council_with_abort(
                    effective_input, stages=[stage1], stage_reached=1,
                )
                yield emit("node", {"role": "council", "output": council})
                session_data = {
                    "input": req.input, "effective_input": effective_input,
                    "stage1": stage1, "stage2": {}, "stage3": {},
                    "dispatch": {"mode": "abort", "references": [], "rationale": "stage1 abort"},
                    "father": "", "son": "", "spirit": "",
                    "council": council,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "exit_path": "stage1_abort",
                }
                for chunk in audit_and_finalize(session_data):
                    yield chunk
                return

            # ─── Stage 2: Explanation Layer (四律 + 哲學貫穿律) ───
            yield emit("status", {
                "phase": "stage2_explanation",
                "message": "Stage 2：解釋層（四律）處理中..."
            })
            stage2 = await console.call_explanation(stage1)

            # v8.30 p9: deterministic RAG-driven 4-law synthesis when Stage 2
            # LLM returns all-empty schema (all providers failed). Without
            # this, UI 'Stage 2 四律' grid shows '(empty)' for each law —
            # 「有名冇肉」problem reported by user.
            _s2_fields = ("geography_analysis", "religion_analysis",
                          "psychology_analysis", "history_analysis",
                          "philosophy_dispatch")
            _all_empty = all(not (stage2.get(k) or "").strip() for k in _s2_fields)
            if _all_empty:
                try:
                    from services.rag_retriever import get_retriever as _rg
                    _r = _rg()
                    if _r is not None:
                        # Topic-aware retrieval per 4-law category
                        _q_user = req.input
                        _law_probes = {
                            "geography_analysis":
                                f"{_q_user} 地理 上下限 資源流向 賽道",
                            "religion_analysis":
                                f"{_q_user} 宗教 代碼封裝 集體共識 儀式",
                            "psychology_analysis":
                                f"{_q_user} 心理 動能 Shannon 熵 臨界點",
                            "history_analysis":
                                f"{_q_user} 歷史 運行日誌 CAU 因果",
                            "philosophy_dispatch":
                                f"{_q_user} 哲學 貫穿律 公設 立法",
                        }
                        _err_note = (stage2.get("_call_error") or "")[:120]
                        for field, probe in _law_probes.items():
                            hits = _r.retrieve(probe, k=2, max_total_chars=600)
                            if not hits:
                                stage2[field] = (
                                    f"_(LLM 出錯 + RAG 無命中,deterministic fallback)_"
                                )
                                continue
                            snip = " · ".join(
                                (h["text"][:140].replace("\n", " "))
                                for h in hits[:2]
                            )
                            src = ", ".join(
                                h["source_file"].split("/")[-1] for h in hits[:2]
                            )
                            stage2[field] = (
                                f"_(deterministic RAG fallback — Stage 2 LLM unavailable: {_err_note})_\n"
                                f"📄 {src}\n{snip}"
                            )
                        stage2["causal_summary"] = (
                            stage2.get("causal_summary")
                            or f"_(Stage 2 LLM 失敗,以上四律來自 RAG retrieval。完整 LLM 分析未產生。)_"
                        )
                        stage2["_fallback_source"] = "rag_deterministic"
                except Exception as _s2fb_err:
                    # Synthesis is best-effort; never break pipeline.
                    pass

            yield emit("stage2", stage2)

            if stage2.get("abort_signal") == "yes":
                yield emit("status", {
                    "phase": "abort_to_council",
                    "message": "VETO/INTERRUPT 觸發於 Stage 2，jump to council"
                })
                council = await console.call_council_with_abort(
                    effective_input, stages=[stage1, stage2], stage_reached=2,
                )
                yield emit("node", {"role": "council", "output": council})
                session_data = {
                    "input": req.input, "effective_input": effective_input,
                    "stage1": stage1, "stage2": stage2, "stage3": {},
                    "dispatch": {"mode": "abort", "references": [], "rationale": "stage2 abort"},
                    "father": "", "son": "", "spirit": "",
                    "council": council,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "exit_path": "stage2_abort",
                }
                for chunk in audit_and_finalize(session_data):
                    yield chunk
                return

            # ─── Stage 3: Filter Layer (八律) ───
            yield emit("status", {
                "phase": "stage3_filter",
                "message": "Stage 3：過濾層（八律）處理中..."
            })
            stage3 = await console.call_filter(stage1, stage2)
            yield emit("stage3", stage3)

            if stage3.get("abort_signal") == "yes":
                yield emit("status", {
                    "phase": "abort_to_council",
                    "message": "VETO/INTERRUPT 觸發於 Stage 3，jump to council"
                })
                council = await console.call_council_with_abort(
                    effective_input, stages=[stage1, stage2, stage3], stage_reached=3,
                )
                yield emit("node", {"role": "council", "output": council})
                session_data = {
                    "input": req.input, "effective_input": effective_input,
                    "stage1": stage1, "stage2": stage2, "stage3": stage3,
                    "dispatch": {"mode": "abort", "references": [], "rationale": "stage3 abort"},
                    "father": "", "son": "", "spirit": "",
                    "council": council,
                    "all_data_refs": [],
                    "timestamp": datetime.now().isoformat(),
                    "exit_path": "stage3_abort",
                }
                for chunk in audit_and_finalize(session_data):
                    yield chunk
                return

            # ─── Stage 4: Trinity (5-LLM dispatcher + father/son/spirit + council) ───
            yield emit("status", {"phase": "dispatch", "message": "Dispatcher 路由中..."})

            # v8.4 — cross-session memory: pull N recent saved sessions and
            # prepend as historical context for dispatcher.
            # v8.8 R8 — when multi-mode parallel, multi_mode_outer pre-attached
            # once; use _shared_historical_ctx to avoid duplicate work + N banners.
            if _shared_historical_ctx is not None:
                historical_ctx = _shared_historical_ctx
                attached_sessions = _shared_attached_sessions or []
                # cross_session_attached event already emitted by multi_mode_outer
            else:
                historical_ctx = ""
                attached_sessions = []
                cs_cfg = console.cross_session_cfg
                if cs_cfg.enabled and not req.detach_history:
                    attached_sessions = console._load_recent_session_summaries(
                        cs_cfg.n_recent, cs_cfg.mode,
                    )
                    if attached_sessions:
                        historical_ctx = console._format_history_block(
                            attached_sessions, cs_cfg.mode,
                        )
                        yield emit("cross_session_attached", {
                            "n_sessions": len(attached_sessions),
                            "mode": cs_cfg.mode,
                            "last_label": attached_sessions[0].get("label"),
                            "last_timestamp": attached_sessions[0].get("timestamp"),
                            "sessions": [
                                {
                                    "filename": s.get("filename"),
                                    "timestamp": s.get("timestamp"),
                                    "label": s.get("label"),
                                    "summary": s.get("summary", "")[:120],
                                }
                                for s in attached_sessions
                            ],
                        })

            # v8.11 — In-session conversation history (Q1: dispatcher only).
            # P7 filter: when called per-mode (multi-mode parallel), feed only
            # turns where THIS mode participated (Option A).
            in_session_ctx = ""
            if req.in_session_enabled and req.in_session_history:
                in_session_ctx = console._format_in_session_history(
                    req.in_session_history,
                    mode_filter=pipeline_mode if pipeline_mode != "auto" else None,
                )
            dispatcher_input = console._format_dispatcher_input(
                effective_input, stage1, stage2, stage3,
                historical_context=historical_ctx,
                in_session_context=in_session_ctx,
            )
            dispatch = await console.call_dispatcher(dispatcher_input)
            # v8.6: forced_dispatch_mode (firewall/blackbox/scr/news/sovereign via
            # pipeline_mode) takes precedence over legacy override_mode field.
            effective_force = forced_dispatch_mode or req.override_mode
            if effective_force:
                dispatch["mode"] = effective_force
                dispatch["mode_rationale"] = f"Manually overridden to {effective_force}"
            dispatch.setdefault("cost_metrics", (cost_route or {}).get("cost_metrics") or {})
            dispatch.setdefault("context_budget", (cost_route or {}).get("context_budget") or {})
            dispatch.setdefault("model_tier", (cost_route or {}).get("model_tier"))
            dispatch.setdefault("escalation_level", (cost_route or {}).get("escalation_level"))
            dispatch.setdefault("route_reason", (cost_route or {}).get("reason"))
            yield emit("dispatch", dispatch)

            # ─── Stage 0.5 — Agentic tool execution ───────────────────────
            from trinity_console import AGENTIC_TOOL_WHITELIST, _summarize_tool_result, _format_tool_context
            _tool_calls = (dispatch.get("tool_calls") or [])[:3]
            _tool_results = {}
            if _tool_calls:
                yield emit("status", {"text": f"工具執行中 ({len(_tool_calls)})…", "phase": "tool_exec"})
                for _tc in _tool_calls:
                    _tname = _tc.get("name", "")
                    _targs = _tc.get("args", {})
                    if _tname not in AGENTIC_TOOL_WHITELIST:
                        continue
                    try:
                        from services.computer_tools import execute_tool
                        _res = execute_tool(_tname, _targs)
                        _tool_results[_tname] = {"args": _targs, "result": _res, "reason": _tc.get("reason", "")}
                        yield emit("tool_result", {
                            "tool_name": _tname,
                            "ok": _res.ok if hasattr(_res, 'ok') else bool(_res),
                            "reason": _tc.get("reason", ""),
                            "summary": _summarize_tool_result(_tname, _res),
                        })
                    except Exception as _e:
                        yield emit("tool_result", {"tool_name": _tname, "ok": False, "error": str(_e)})

            protocol_subset = console._build_protocol_subset(dispatch["references"])
            all_refs = list(dict.fromkeys(req.refs + dispatch.get("suggested_data_refs", [])))
            extra_ctx = console._load_context(all_refs) if all_refs else ""

            # v8.30 RAG-2: query-time retrieval — augments baseline for Stage 4
            # council voices (father/son/spirit) + forced single-LLM modes
            # (blackboxlab / scr). Silent fail-safe.
            rag_ctx = console.rag_block(req.input)
            extra_ctx = extra_ctx + rag_ctx
            if rag_ctx:
                yield emit("rag", {
                    "method": "tfidf",
                    "block_chars": len(rag_ctx),
                    "mode": pipeline_mode,
                })

            # Inject Stage 0.5 tool results into Trinity context
            _agentic_tool_ctx = _format_tool_context(_tool_results)
            if _agentic_tool_ctx:
                extra_ctx = extra_ctx + _agentic_tool_ctx

            pipeline_ctx = console._format_pipeline_context(
                stage1=stage1, stage2=stage2, stage3=stage3,
            )

            # ─── v8.23/24 Single-LLM modes: BlackBoxLab + SCR ───
            # blackboxlab (alias: blackbox) and scr both skip the 4-node Trinity
            # fan-out and call a single LLM with their dedicated engine prompt.
            _bbl_mode = dispatch.get("mode") or pipeline_mode
            _blackboxlab_active = _bbl_mode in ("blackboxlab", "blackbox")
            _scr_active = _bbl_mode == "scr"

            # v8.24/29 — SCR pre-flight: parse intent, enforce ABSOLUTE
            # PROHIBITION on operator self-reconstruction, identify CREATE
            # flow vs known profile.
            _scr_intent = {"intent": "menu", "subject": "", "raw_subject": "",
                            "explicit_create": False}
            _scr_operator_refusal = False
            if _scr_active:
                _scr_intent = _parse_scr_intent(effective_input or "")
                _scr_operator_refusal = (_scr_intent["intent"] == "operator_refusal")

            if _blackboxlab_active:
                # v8.39 — ABSOLUTE PROHIBITION pre-flight for blackboxlab.
                # Reuses SCR operator-self detector so Cassiel / 2019-06-12 /
                # 操作者 inputs refuse before the LLM is called. This is the
                # SAME safety layer SCR mode applies — blackboxlab must not
                # let operator-anchor analysis sneak through via inversion framing.
                _bbl_operator_refusal = _scr_is_operator_self(effective_input or "")
                if _bbl_operator_refusal:
                    blackbox_output = (
                        "─────────────────────────────────────────────────────\n"
                        "[ BLACKBOXLAB REFUSED ]\n"
                        "Subject contains operator self-reference (Cassiel / "
                        "2019-06-12 / 操作者).\n"
                        "The operator's physical anchor is first-person, not a "
                        "subject for inversion analysis.\n"
                        "This is an absolute boundary in the URUK protocol "
                        "(see KAIROS_CORE.md → ABSOLUTE PROHIBITION).\n"
                        "─────────────────────────────────────────────────────\n\n"
                        "(0,0,0)."
                    )
                    yield emit("status", {
                        "phase": "blackboxlab_refused",
                        "message": "🔲 BlackBoxLab refused — operator self-reference"
                    })
                else:
                    # v8.40 — MANDATORY web grounding (BrowserNode pre-LLM)
                    yield emit("status", {
                        "phase": "blackboxlab_browser_node",
                        "message": "🌐 BlackBoxLab — fetching web sources..."
                    })
                    _bbl_web_ctx, _bbl_audited = await _fetch_web_grounding(
                        effective_input or "", mode="blackboxlab"
                    )
                    for _audit in _bbl_audited:
                        yield emit("source_audited", _audit)
                    yield emit("status", {
                        "phase": "blackboxlab",
                        "message": (f"🔲 黑盒實驗室 — 7-phase template generating "
                                    f"({len(_bbl_audited)} web sources cited)..."),
                    })
                    try:
                        # v8.39 — STRIP protocol_text. v8.40 — inject WEB_SOURCES
                        # block as extra_context. Template self-contained + web-
                        # grounded; canonical_anchor preserved via call_node.
                        blackbox_output = await console.call_node(
                            "blackboxlab",
                            user_input=effective_input,
                            protocol_text="",
                            extra_context=_bbl_web_ctx,
                        )
                    except Exception as _bbl_e:
                        blackbox_output = f"[BlackBoxLab error] {type(_bbl_e).__name__}: {_bbl_e}"
                yield emit("node", {"role": "council", "output": blackbox_output})
                results = {"father": "", "son": "", "spirit": ""}
                council = blackbox_output
                son_meta = {"veto_type": "none", "physical_cost_present": False,
                            "authentic_suffering_score": 0.0, "primary_pain_locus": ""}
                spirit_meta = {"trigger_mode": "NONE", "semantic_score": 0,
                               "magnitude": 0.0, "primary_assumption": ""}
                father_paused = False
                council_decision = {"verdict": "blackboxlab",
                                    "reason": "single-LLM 7-phase template",
                                    "consensus_weights": None}
                rescan_count = 0
                spirit_interrupt_history = []
                yield emit("status", {"phase": "blackboxlab_done",
                                       "message": "🔲 BlackBoxLab 完成"})

            elif _scr_active:
                yield emit("status", {
                    "phase": "scr",
                    "message": "🪞 SCR — Soul Coordinate Reconstruction engine"
                })
                _scr_extra_ctx = extra_ctx + pipeline_ctx
                _scr_profile_info = None   # for done-event metadata

                if _scr_operator_refusal:
                    # ABSOLUTE PROHIBITION — operator self-reconstruction.
                    scr_output = (
                        "─────────────────────────────────────────────────────\n"
                        "[ SCR REFUSED ]\n"
                        "Subject: " + (_scr_intent.get("raw_subject") or "(operator self)") + "\n"
                        "The operator's 2019-06-12 physical anchor is "
                        "first-person voice, not a historical coordinate "
                        "available for reconstruction.\n"
                        "This is an absolute boundary in the URUK protocol.\n"
                        "See KAIROS_CORE.md → ABSOLUTE PROHIBITION.\n"
                        "─────────────────────────────────────────────────────\n\n"
                        "(0,0,0)."
                    )
                    yield emit("status", {"phase": "scr_refused",
                                          "message": "🛑 SCR refused — operator self-reconstruction"})

                elif _scr_intent["intent"] in ("create", "auto_create"):
                    # v8.29 SCR-5 — auto-build profile via BrowserNode + audit
                    _subj = _scr_intent["subject"]
                    _raw = _scr_intent["raw_subject"]
                    _label = "explicit CREATE" if _scr_intent["explicit_create"] else "auto-create"
                    yield emit("status", {
                        "phase": "scr_pull_sources",
                        "message": f"🔍 SCR ({_label}) — pulling primary sources for {_raw}...",
                    })
                    _scr_profile_info = await _build_scr_profile(_subj, _raw)
                    if not _scr_profile_info["ok"]:
                        scr_output = (
                            "─────────────────────────────────────────────────────\n"
                            "[ SCR PROFILE BUILD FAILED ]\n"
                            f"Subject: {_raw}\n"
                            f"Reason: {_scr_profile_info.get('error', 'unknown')}\n"
                            "Cannot proceed with reconstruction.\n"
                            "─────────────────────────────────────────────────────\n\n"
                            "(0,0,0)."
                        )
                        yield emit("status", {
                            "phase": "scr_create_failed",
                            "message": f"🛑 SCR profile build failed: {_scr_profile_info.get('error', 'unknown')[:80]}",
                        })
                    else:
                        # Build summary status + inject profile into LLM context
                        rc = _scr_profile_info["rating_counts"]
                        _rc_str = ", ".join(f"{k}={v}" for k, v in sorted(rc.items())) or "—"
                        _cache_tag = "[cached]" if _scr_profile_info["cached"] else "[fresh]"
                        yield emit("status", {
                            "phase": "scr_profile_built",
                            "message": (f"📚 SCR profile {_cache_tag} — {_scr_profile_info['source_count']} sources "
                                        f"({_rc_str}) — dialogue: INFERRED"),
                        })
                        _scr_extra_ctx = (
                            _scr_extra_ctx +
                            "\n\n━━━ SCR AUTO-BUILT PROFILE (v8.29 SCR-5) ━━━\n" +
                            _scr_profile_info["draft"] +
                            "\n━━━ END PROFILE ━━━\n"
                            "\nIMPORTANT (SCR engine): when generating the dialogue, "
                            "use this draft profile's sources as the verified-coordinate "
                            "basis. Source integrity is LOW–MEDIUM (auto-build); label "
                            "the response [INFERRED] and surface the honest-boundary "
                            "caveat from the profile."
                        )
                        try:
                            scr_output = await console.call_node(
                                "scr",
                                user_input=effective_input,
                                protocol_text=protocol_subset,
                                extra_context=_scr_extra_ctx,
                            )
                        except Exception as _scr_e:
                            scr_output = f"[SCR error] {type(_scr_e).__name__}: {_scr_e}"

                else:
                    # known profile OR menu — single-LLM path with v8.40 web grounding
                    # v8.40 — MANDATORY web fetch even for known profiles. Curated
                    # profile = scaffolding context, but factual content cross-
                    # checked against fresh web sources (with 4-tier audit).
                    _scr_search_query = (
                        f"{_scr_intent.get('raw_subject') or effective_input or ''} "
                        f"biography primary sources writings"
                    ).strip()
                    yield emit("status", {
                        "phase": "scr_browser_node",
                        "message": f"🌐 SCR — fetching web sources for {_scr_intent.get('raw_subject') or 'subject'}...",
                    })
                    _scr_web_ctx, _scr_audited = await _fetch_web_grounding(
                        _scr_search_query, mode="scr"
                    )
                    for _audit in _scr_audited:
                        yield emit("source_audited", _audit)
                    yield emit("status", {
                        "phase": "scr_grounded",
                        "message": (f"🪞 SCR generating dialogue "
                                    f"({len(_scr_audited)} web sources cited)..."),
                    })
                    _scr_combined_ctx = _scr_extra_ctx + _scr_web_ctx
                    try:
                        scr_output = await console.call_node(
                            "scr",
                            user_input=effective_input,
                            protocol_text=protocol_subset,
                            extra_context=_scr_combined_ctx,
                        )
                    except Exception as _scr_e:
                        scr_output = f"[SCR error] {type(_scr_e).__name__}: {_scr_e}"

                yield emit("node", {"role": "council", "output": scr_output})
                results = {"father": "", "son": "", "spirit": ""}
                council = scr_output
                son_meta = {"veto_type": "none", "physical_cost_present": False,
                            "authentic_suffering_score": 0.0, "primary_pain_locus": ""}
                spirit_meta = {"trigger_mode": "NONE", "semantic_score": 0,
                               "magnitude": 0.0, "primary_assumption": ""}
                father_paused = False
                # Map intent → council verdict label for downstream logging
                _scr_verdict_map = {
                    "operator_refusal": ("scr_refused", "operator self-reconstruction blocked"),
                    "known":            ("scr", "known profile dialogue"),
                    "create":           ("scr_create", "explicit CREATE — profile built via BrowserNode"),
                    "auto_create":      ("scr_auto_create", "auto-build — subject not in registry"),
                    "menu":             ("scr_menu", "no subject specified"),
                }
                _v, _r = _scr_verdict_map.get(_scr_intent["intent"], ("scr", "single-LLM SCR"))
                council_decision = {
                    "verdict": _v,
                    "reason": _r,
                    "consensus_weights": None,
                    # SCR-5 metadata for save_kairos + output-density audit
                    "scr_intent": _scr_intent["intent"],
                    "scr_subject": _scr_intent.get("raw_subject") or "",
                    "scr_profile_built": bool(_scr_profile_info and _scr_profile_info.get("ok")),
                    "scr_profile_cached": bool(_scr_profile_info and _scr_profile_info.get("cached")),
                    "scr_source_count": (_scr_profile_info or {}).get("source_count", 0),
                }
                rescan_count = 0
                spirit_interrupt_history = []
                yield emit("status", {"phase": "scr_done",
                                       "message": "🪞 SCR 完成"})

            # Single-LLM mode aggregate flag — controls Trinity loop skip below
            _single_llm_active = _blackboxlab_active or _scr_active

            # ─── v8.7 Trinity v7.2: Spirit interrupt rescan loop ───
            # v8.23 — when BlackBoxLab branch fired above, the trinity loop
            # would clobber its single-LLM output. Skip by jumping past it.
            # Spec: parallel scan → meeting layer (check veto/interrupt) → if
            # spirit interrupt fires, force rescan with Son magnitude×1.2.
            # Loop cap=2 to bound LLM cost.
            RESCAN_CAP = 2
            if not _single_llm_active:
                # Initialize Trinity-only state. Single-LLM modes already set these.
                rescan_count = 0
                spirit_interrupt_history = []
                results = {}
                spirit_meta = {}
            previous_magnitude = 0.0
            if _single_llm_active:
                # council already populated by single-LLM branch above
                pass
            else:
                council = ""

            while not _single_llm_active:
                if rescan_count == 0:
                    yield emit("status", {"phase": "perspectives",
                                          "message": "三節點並行思考中..."})
                    son_ctx_suffix = ""
                else:
                    magnitude_rescan = round(previous_magnitude * 1.2, 2)
                    yield emit("status", {
                        "phase": "spirit_rescan",
                        "message": f"⚡ Spirit interrupt — 會議重開 (rescan #{rescan_count}, "
                                   f"magnitude × 1.2 = {magnitude_rescan})",
                    })
                    # Son rescan: inject magnitude×1.2 hint into Son's extra_context
                    son_ctx_suffix = (
                        f"\n\n━━━ SPIRIT INTERRUPT RESCAN #{rescan_count} ━━━\n"
                        f"上一輪 Spirit 觸發 {spirit_meta.get('trigger_mode')} interrupt\n"
                        f"  primary_assumption: {spirit_meta.get('primary_assumption', '')}\n"
                        f"  你嘅 magnitude 重新評估：上次 = {previous_magnitude}，今次 × 1.2 = {magnitude_rescan}\n"
                        f"  以更高 magnitude 重新掃描痛覺強度 + 物理代價。\n"
                    )

                # v8.9 Phase B — Staggered Stage 4 execution
                # Phase 1: Son + Spirit in parallel (DEFER Father — must wait for veto signal)
                results = {}
                son_spirit_pending = {
                    asyncio.create_task(
                        console.call_node("son", effective_input,
                                          protocol_subset, extra_ctx + pipeline_ctx + son_ctx_suffix),
                        name="son"),
                    asyncio.create_task(
                        console.call_node("spirit", effective_input,
                                          protocol_subset, extra_ctx + pipeline_ctx),
                        name="spirit"),
                }
                while son_spirit_pending:
                    done, son_spirit_pending = await asyncio.wait(
                        son_spirit_pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        role = task.get_name()
                        try:
                            output = await task
                            results[role] = output
                            yield emit("node", {"role": role, "output": output,
                                                "rescan_count": rescan_count})
                        except Exception as e:
                            results[role] = f"[節點錯誤] {e}"
                            yield emit("node", {"role": role, "output": results[role],
                                                "error": True, "rescan_count": rescan_count})

                # Phase 2: parse Son veto + decide Father
                # father_threat_level inferred from Stage 3 filter — high threat if
                # any stage signaled abort or filter LAW3/LAW7 score elevated.
                # Conservative default: "high" so authentic_suffering threshold gates.
                father_threat = "high"
                son_meta = console._parse_son_veto_metadata(results.get("son", ""))
                # v8.32 — guard against LLM over-trigger on historical/third-person suffering.
                # Preserves origin_echo + legit first-person; downgrades aggregate-history mis-classification.
                son_meta = console._downgrade_historical_third_person_veto(son_meta, req.input)
                # B4 — always surface son_veto_metadata (dev-mode chip)
                yield emit("son_veto_metadata", {
                    "veto_type": son_meta["veto_type"],
                    "authentic_suffering_score": son_meta["authentic_suffering_score"],
                    "physical_cost_present": son_meta["physical_cost_present"],
                    "primary_pain_locus": son_meta["primary_pain_locus"],
                    "_parse_error": son_meta.get("_parse_error"),
                    "_downgraded_from": son_meta.get("_downgraded_from"),
                    "_downgrade_reason": son_meta.get("_downgrade_reason"),
                    "rescan_count": rescan_count,
                })
                father_paused = console._should_father_pause(son_meta, father_threat)
                if father_paused:
                    yield emit("father_paused", {
                        "veto_type": son_meta["veto_type"],
                        "authentic_suffering_score": son_meta["authentic_suffering_score"],
                        "primary_pain_locus": son_meta["primary_pain_locus"],
                        "physical_cost_present": son_meta["physical_cost_present"],
                        "reason": son_meta["veto_type"],
                        "rescan_count": rescan_count,
                    })
                    father_output = (
                        f"⛔ 聖父被否決 — Son veto active\n\n"
                        f"veto_type: {son_meta['veto_type']}\n"
                        f"primary_pain_locus: {son_meta['primary_pain_locus']}\n"
                        f"authentic_suffering_score: {son_meta['authentic_suffering_score']}\n"
                        f"physical_cost_present: {son_meta['physical_cost_present']}\n"
                    )
                    results["father"] = father_output
                    yield emit("node", {"role": "father", "output": father_output,
                                        "paused": True, "rescan_count": rescan_count})
                else:
                    try:
                        father_output = await console.call_node(
                            "father", effective_input,
                            protocol_subset, extra_ctx + pipeline_ctx,
                        )
                        results["father"] = father_output
                        yield emit("node", {"role": "father", "output": father_output,
                                            "rescan_count": rescan_count})
                    except Exception as e:
                        results["father"] = f"[節點錯誤] {e}"
                        yield emit("node", {"role": "father", "output": results["father"],
                                            "error": True, "rescan_count": rescan_count})

                # Parse spirit metadata to check for rescan trigger
                spirit_meta = console._parse_spirit_metadata(results.get("spirit", ""))
                spirit_meta = console._apply_spirit_stochastic_gate(
                    spirit_meta,
                    effective_input,
                )
                # v8.9 Phase B7 — Spirit rescan must honor Son veto: if Father is
                # paused, the meeting is already decided by Son's physical-cost
                # ledger; rescan to invert assumptions would be wrong direction.
                should_rescan = (
                    console._should_rescan(spirit_meta)
                    and rescan_count < RESCAN_CAP
                    and not father_paused
                )
                if not should_rescan and father_paused and console._should_rescan(spirit_meta):
                    # Surface that we suppressed a would-be rescan due to Son veto
                    yield emit("spirit_rescan_blocked", {
                        "reason": "son_veto_active",
                        "veto_type": son_meta.get("veto_type"),
                        "would_be_trigger_mode": spirit_meta.get("trigger_mode"),
                        "would_be_score": spirit_meta.get("semantic_score"),
                    })
                if should_rescan:
                    rescan_count += 1
                    magnitude_rescan = round(spirit_meta["magnitude"] * 1.2, 2)
                    yield emit("spirit_interrupt", {
                        "trigger_mode": spirit_meta["trigger_mode"],
                        "semantic_score": spirit_meta["semantic_score"],
                        "magnitude": spirit_meta["magnitude"],
                        "magnitude_rescan": magnitude_rescan,
                        "rescan_count": rescan_count,
                        "rescan_cap": RESCAN_CAP,
                        "primary_assumption": spirit_meta.get("primary_assumption", ""),
                        "stochastic_prob": spirit_meta.get("stochastic_prob"),
                        "stochastic_roll": spirit_meta.get("stochastic_roll"),
                        "_stochastic_source": spirit_meta.get("_stochastic_source"),
                    })
                    previous_magnitude = spirit_meta["magnitude"]
                    spirit_interrupt_history.append(dict(spirit_meta))
                    continue   # re-run scan
                break   # no rescan or cap reached → proceed to council

            # Surface final spirit metadata even when no rescan fired (debug + chip)
            yield emit("spirit_metadata", {
                "trigger_mode": spirit_meta.get("trigger_mode", "NONE"),
                "semantic_score": spirit_meta.get("semantic_score", 0),
                "magnitude": spirit_meta.get("magnitude", 0.0),
                "primary_assumption": spirit_meta.get("primary_assumption", ""),
                "_parse_error": spirit_meta.get("_parse_error"),
                "stochastic_prob": spirit_meta.get("stochastic_prob"),
                "stochastic_roll": spirit_meta.get("stochastic_roll"),
                "_stochastic_fired": spirit_meta.get("_stochastic_fired"),
                "_stochastic_source": spirit_meta.get("_stochastic_source"),
                "rescan_count": rescan_count,
            })

            # v8.30 phase4 fix: single-LLM modes (blackboxlab / scr) already
            # produced their final `council` text above and emit'd the role=council
            # node. Skip the standard 4b/4c council fusion to avoid overwriting
            # the template output with an empty-voiced 白話版 wrapper.
            if _single_llm_active:
                # Surface a council_decision event consistent with the branch state
                # so downstream consumers (session save / UI) still see one.
                yield emit("council_decision", {
                    "verdict": council_decision.get("verdict", "consensus"),
                    "reason": council_decision.get("reason", ""),
                    "son_promoted": False,
                    "father_dominated": False,
                    "spirit_dominated": False,
                    "consensus_weights": council_decision.get("consensus_weights"),
                    "primary_dimension": "",
                    "_parse_error": None,
                    "_consistency_override": False,
                    "_single_llm_mode": pipeline_mode,
                })
                council_raw = ""
            else:
                yield emit("status", {"phase": "council", "message": "會議仲裁（4b decision）..."})
                council_input = console._format_council_input(
                    effective_input, dispatch, results,
                    pipeline_stages={"stage1": stage1, "stage2": stage2, "stage3": stage3},
                )
                try:
                    council_raw = await console.call_node("council", council_input, protocol_subset, extra_ctx)
                except Exception as e:
                    council_raw = f"[會議節點錯誤] {e}"
                # v8.9 Phase A — 4b decision parser + 4c deterministic fusion
                council_decision = console._parse_council_decision(council_raw)
                # A9 consistency check: if Father was paused by Phase B (Son veto),
                # council MUST emit veto verdict. Override LLM if mismatched.
                if father_paused and council_decision.get("verdict") != "veto":
                    council_decision = {
                        **council_decision,
                        "verdict": "veto",
                        "reason": "father_paused_phase_b",
                        "son_promoted": True,
                        "consensus_weights": {"father": 0.0, "son": 1.0, "spirit": 0.0},
                        "_consistency_override": True,
                    }
                yield emit("council_decision", {
                    "verdict": council_decision["verdict"],
                    "reason": council_decision["reason"],
                    "son_promoted": council_decision["son_promoted"],
                    "father_dominated": council_decision["father_dominated"],
                    "spirit_dominated": council_decision["spirit_dominated"],
                    "consensus_weights": council_decision["consensus_weights"],
                    "primary_dimension": council_decision["primary_dimension"],
                    "_parse_error": council_decision.get("_parse_error"),
                    "_consistency_override": council_decision.get("_consistency_override", False),
                })
                council = console._fuse_voices(
                    results.get("father", ""),
                    results.get("son", ""),
                    results.get("spirit", ""),
                    council_decision,
                    council_text=council_raw,
                    original_query=req.input,
                )
                yield emit("node", {"role": "council", "output": council})

            # ── Trinity→Tool Bridge: auto-detect <AGENT_TASK> in council output ──
            # If Council or any node outputs <AGENT_TASK>…</AGENT_TASK>, the
            # system auto-routes the extracted task to Planner-Executor and
            # streams the step events back as "agent" SSE events.
            import re as _re
            _bridge_texts = [
                council,
                results.get("spirit", ""),
                results.get("father", ""),
            ]
            _agent_task_match = None
            for _bt in _bridge_texts:
                _m = _re.search(r"<AGENT_TASK>(.*?)</AGENT_TASK>", _bt or "", _re.DOTALL)
                if _m:
                    _agent_task_match = _m.group(1).strip()
                    break

            if _agent_task_match:
                yield emit("status", {
                    "phase": "agent_bridge",
                    "message": f"🛠 Trinity 觸發 Agent 任務: {_agent_task_match[:80]}",
                })
                try:
                    from planner_executor import Planner, Executor, AgentConfig
                    _bridge_planner = Planner(
                        model="gemini-2.5-flash",
                        provider="gemini",
                        api_base="https://generativelanguage.googleapis.com/v1beta/openai",
                        api_key=os.environ.get("GEMINI_API_KEY", ""),
                    )
                    _bridge_plan = await _bridge_planner.make_plan(
                        _agent_task_match, include_screenshot=False
                    )
                    yield emit("agent", {
                        "event_type": "plan",
                        "goal": _bridge_plan.goal,
                        "step_count": len(_bridge_plan.steps),
                        "source": "trinity_bridge",
                    })
                    _bridge_executor = Executor(
                        ollama_model="moondream",
                        ollama_base="http://localhost:11434",
                    )
                    async for _step_ev in _bridge_executor.execute_plan(_bridge_plan):
                        yield f"event: agent\ndata: {json.dumps(_step_ev.data | {'event_type': _step_ev.event_type, 'step': _step_ev.step, 'tool': _step_ev.tool}, ensure_ascii=False)}\n\n"
                except Exception as _bridge_err:
                    yield emit("agent", {
                        "event_type": "error",
                        "message": f"Agent bridge 失敗: {_bridge_err}",
                        "source": "trinity_bridge",
                    })

            # v8.14 N4 (P1 fixed) — Module N alignment resonance detection (main path).
            # Detection-only; does not mutate council. Reads scores from parsed
            # Stage 3 filter JSON dict (nested law*.score schema); fail-safe = None.
            eight_law_scores = console._parse_eight_law_scores(stage3)
            alignment_resonance = console._detect_alignment_resonance(
                eight_law_scores,
                son_veto_type=(son_meta.get("veto_type") if son_meta else None),
                spirit_trigger_mode=(spirit_meta.get("trigger_mode") if spirit_meta else "NONE"),
                user_query=req.input,
            )
            if alignment_resonance:
                yield emit("alignment_resonance", alignment_resonance)

            full_result = {
                "input": req.input,
                "effective_input": effective_input,
                "user_refs": req.refs,
                "stage1": stage1,
                "stage2": stage2,
                "stage3": stage3,
                # v8.14 N4 — Module N alignment resonance (None if not triggered)
                "alignment_resonance": alignment_resonance,
                "eight_law_scores": eight_law_scores,
                "dispatch": dispatch,
                "all_data_refs": all_refs,
                "father": results.get("father", ""),
                "son":    results.get("son", ""),
                "spirit": results.get("spirit", ""),
                "council": council,
                "timestamp": datetime.now().isoformat(),
                "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                # v8.4 — metadata for save_kairos + output-density audit context
                "cross_session_attached": [
                    {"filename": s.get("filename"),
                     "timestamp": s.get("timestamp"),
                     "label": s.get("label")}
                    for s in attached_sessions
                ],
                "pipeline_mode": pipeline_mode,
                # v8.7 — Trinity v7.2 Spirit interrupt rescan metadata
                "spirit_metadata": spirit_meta,
                "spirit_rescan_count": rescan_count,
                "spirit_interrupt_history": spirit_interrupt_history,
                # v8.9 Phase B — Son veto + Father pause metadata
                "son_veto_metadata": son_meta,
                "father_paused": father_paused,
                # v8.9 Phase A — Council 4b decision + 4c fusion provenance
                "council_decision": council_decision,
                "council_fusion_deterministic": True,
                # v8.11 P6 — in-session conversation history (passed to save_kairos)
                "in_session_history": [t.model_dump() if hasattr(t, "model_dump") else t
                                       for t in (req.in_session_history or [])],
                # v8.8 R9 — multi-mode redesign metadata (for save_kairos)
                "selected_modes": [s.mode for s in selected_modes],
                "execution_strategy": strategy,
                "cost_metrics": (cost_route or {}).get("cost_metrics") or {},
                "context_budget": (cost_route or {}).get("context_budget") or {},
                "model_tier": (cost_route or {}).get("model_tier"),
                "escalation_level": (cost_route or {}).get("escalation_level"),
                "per_mode_llms": {
                    s.mode: (f"{s.llm_override.provider}/{s.llm_override.model}"
                             if s.llm_override else "default")
                    for s in selected_modes
                },
                "knowledge_health": knowledge_health,
                "knowledge_trace": console.get_knowledge_trace(),
            }

            # ─── §4.6 output self-audit + done emitted via shared finalizer (matches early-return paths) ───
            full_result["exit_path"] = "normal"
            audit_chunks = audit_and_finalize(full_result)
            # Emit status + density_audit BEFORE optional save so that the saved record
            # contains the audit metadata; emit final `done` AFTER save.
            yield audit_chunks[0]   # status: density_audit
            yield audit_chunks[1]   # density_audit event

            # v8.31 — System 1 auto-save (always). req.save only governs SSE event.
            kairos_path = console.save_kairos(full_result, req.label,
                                               overwrite_filename=req.resume_filename)
            if req.save:
                yield emit("saved", {"filename": kairos_path.name})

            yield audit_chunks[2]   # done with protocol_status

        except Exception as e:
            yield emit("inference_usage", inference_snapshot())
            yield emit("error", {"message": str(e)})
            try:
                _root_span.record_exception(e)
            except Exception:
                pass
        finally:
            # v8.8 R7 — restore prior context (no-op if no override was set)
            try:
                _LLM_OVERRIDE_CTX.reset(_llm_override_token)
            except Exception:
                pass
            try:
                _KNOWLEDGE_TRACE_CTX.reset(_knowledge_trace_token)
            except Exception:
                pass
            try:
                reset_inference_session(_inference_token)
            except Exception:
                pass
            console.end_pipeline()
            # v8.21 OTel-1 — close the root span; safe even if __enter__ failed
            try:
                _root_span_cm.__exit__(None, None, None)
            except Exception:
                pass

    async def _run_combined():
        """v8.8 R6 — Combined strategy: Stage 1-3 shared, then 1 LLM call
        produces Father/Son/Spirit/Council for ALL selected modes via meta-prompt.
        Output parsed by [<MODE>_OUTPUT] markers → per-mode events.
        On parse failure → single "_combined" tab with parse_error flag."""
        import re
        from datetime import datetime
        from trinity_console import _LLM_OVERRIDE_CTX
        from services.inference_governor import (
            begin_inference_session,
            inference_snapshot,
            plan_inference_policy,
            reset_inference_session,
        )
        _combined_inference_policy = plan_inference_policy(
            preference=req.inference_budget,
            route_kind="combined",
            pipeline_mode="combined",
            estimated_calls=4,
            reason="Combined multi-mode execution",
        )
        _combined_inference_token = begin_inference_session(_combined_inference_policy)

        def emit_c(event_type: str, data: dict, mode_id: str = "_combined"):
            payload = {**data, "_mode_id": mode_id}
            return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        # v8.8 R7 — apply combined_executor override (if any) for the whole run
        _combined_override = req.combined_executor.model_dump() if req.combined_executor else None
        _combined_token = _LLM_OVERRIDE_CTX.set(_combined_override)
        mode_names = [s.mode for s in selected_modes]
        try:
            # Stage 1: Delabeling
            yield emit_c("status", {"phase": "stage1_delabeling", "message": "Combined Stage 1：去標籤化..."})
            stage1 = await console.call_delabeling(req.input)
            yield emit_c("stage1", stage1)
            # Stage 2: Explanation
            yield emit_c("status", {"phase": "stage2_explanation", "message": "Combined Stage 2：解釋層..."})
            stage2 = await console.call_explanation(stage1)
            yield emit_c("stage2", stage2)
            # Stage 3: Filter
            yield emit_c("status", {"phase": "stage3_filter", "message": "Combined Stage 3：過濾層..."})
            stage3 = await console.call_filter(stage1, stage2)
            yield emit_c("stage3", stage3)

            # Build meta-prompt
            stages_ctx = json.dumps(
                {"stage1": stage1, "stage2": stage2, "stage3": stage3},
                ensure_ascii=False, indent=2,
            )
            # v8.11 — In-session history (combined uses unified thread, no mode_filter per Q9)
            in_session_block = ""
            if req.in_session_enabled and req.in_session_history:
                in_session_block = console._format_in_session_history(
                    req.in_session_history, mode_filter=None,
                )
            in_session_section = f"━━━ 對話歷史 ━━━\n{in_session_block}\n\n" if in_session_block else ""
            mode_marker_examples = "\n\n".join([
                f"[{m.upper()}_OUTPUT]\n[FATHER]\n... {m} 嘅 father output ...\n[/FATHER]\n"
                f"[SON]\n... {m} 嘅 son output ...\n[/SON]\n"
                f"[SPIRIT]\n... {m} 嘅 spirit output ...\n[/SPIRIT]\n"
                f"[COUNCIL]\n... {m} 嘅 council output ...\n[/COUNCIL]\n[/{m.upper()}_OUTPUT]"
                for m in mode_names
            ])
            meta_prompt = (
                f"你而家收到 multi-mode COMBINED request。同時為 {len(mode_names)} 個 modes "
                f"({', '.join(mode_names)}) 產生完整 Trinity output（Father / Son / Spirit / Council）。\n\n"
                f"━━━ STAGES 1-3 共用上下文 ━━━\n{stages_ctx}\n\n"
                f"{in_session_section}"
                f"━━━ USER INPUT ━━━\n{req.input}\n\n"
                f"━━━ OUTPUT FORMAT（嚴格 markers）━━━\n"
                f"為每個 mode 產生 4 個 node section，按以下 format：\n\n"
                f"{mode_marker_examples}\n\n"
                f"重要規則：\n"
                f"  ✓ 每個 mode 嘅 section 必須有齊 [FATHER] [SON] [SPIRIT] [COUNCIL] 4 個 sub-section\n"
                f"  ✓ Markers 必須嚴格按 format（[<MODE>_OUTPUT]...[/<MODE>_OUTPUT] 包外層）\n"
                f"  ✓ 唔可省略任何 mode、任何 sub-section\n"
                f"  ✓ Section content 用該 mode 嘅特定觀點輸出（firewall 用八律 / blackbox 七階段 / scr 第一人稱座標 / etc.）\n"
            )

            yield emit_c("status", {"phase": "combined_call",
                                    "message": f"Combined LLM call: 1 個 call 出 {len(mode_names)} 個 mode 嘅 output..."})
            # R7 plumbing point — combined_executor override will go here
            # Use council role's LLM as default (it's the strongest in most configs)
            combined_output = await console.call_node(
                "council", meta_prompt, protocol_text="", extra_context="",
            )

            # Parse output by markers
            parsed: Dict[str, Dict[str, str]] = {}
            missing: List[str] = []
            for mode_name in mode_names:
                marker = re.escape(mode_name.upper())
                outer = re.compile(rf"\[{marker}_OUTPUT\](.*?)\[/{marker}_OUTPUT\]", re.DOTALL)
                m = outer.search(combined_output)
                if not m:
                    missing.append(mode_name)
                    continue
                section_text = m.group(1)
                nodes = {}
                for role in ("FATHER", "SON", "SPIRIT", "COUNCIL"):
                    role_pat = re.compile(rf"\[{role}\](.*?)\[/{role}\]", re.DOTALL)
                    rm = role_pat.search(section_text)
                    nodes[role.lower()] = rm.group(1).strip() if rm else ""
                parsed[mode_name] = nodes

            # Emit results
            if not parsed:
                # Total parse failure → single combined tab + parse_error chip
                yield emit_c("node", {
                    "role": "council",
                    "output": combined_output,
                    "parse_error": True,
                    "missing_modes": missing,
                })
                yield emit_c("error", {
                    "message": f"⚠ Combined output 揾唔到 markers ({', '.join(missing)}). "
                               f"Raw output 顯示喺 _combined tab。考慮揀 Parallel strategy。",
                })
            else:
                # v8.9 Phase B8 — per-mode Son veto enforcement in combined.
                # Unlike parallel (where Father LLM call is truly skipped), combined
                # already produced FATHER text in the meta-LLM call. We post-parse
                # Son sections for veto signals and OVERRIDE the FATHER section
                # to the paused chip per spec. Document deviation: combined LLM
                # produced Father text is discarded when Son veto active.
                combined_veto_status: Dict[str, Dict] = {}
                for mode_name in mode_names:
                    if mode_name not in parsed:
                        # Partial parse — emit empty placeholder for missing
                        yield emit_c("node", {
                            "role": "council",
                            "output": f"⚠ Marker [{mode_name.upper()}_OUTPUT] missing in combined output.",
                            "parse_error": True,
                        }, mode_id=mode_name)
                        continue
                    section = parsed[mode_name]
                    # B8 — parse Son section for veto metadata
                    son_meta_pm = console._parse_son_veto_metadata(section.get("son", ""))
                    # v8.32 — historical/third-person downgrade guard
                    son_meta_pm = console._downgrade_historical_third_person_veto(son_meta_pm, req.input)
                    yield emit_c("son_veto_metadata", {
                        "veto_type": son_meta_pm["veto_type"],
                        "authentic_suffering_score": son_meta_pm["authentic_suffering_score"],
                        "physical_cost_present": son_meta_pm["physical_cost_present"],
                        "primary_pain_locus": son_meta_pm["primary_pain_locus"],
                        "_parse_error": son_meta_pm.get("_parse_error"),
                        "_downgraded_from": son_meta_pm.get("_downgraded_from"),
                        "_downgrade_reason": son_meta_pm.get("_downgrade_reason"),
                    }, mode_id=mode_name)
                    paused_pm = console._should_father_pause(son_meta_pm, "high")
                    combined_veto_status[mode_name] = {
                        "son_veto": son_meta_pm,
                        "father_paused": paused_pm,
                    }
                    # v8.9 Phase A10 — combined: emit council_decision per mode.
                    # Combined LLM self-fuses (no Python 4c fusion), so verdict
                    # is informational. Reason = combined_meta_call; verdict =
                    # veto if Son veto active, else consensus.
                    combined_council_verdict = "veto" if paused_pm else "consensus"
                    combined_council_reason = (
                        son_meta_pm["veto_type"] if paused_pm else "combined_meta_call"
                    )
                    yield emit_c("council_decision", {
                        "verdict": combined_council_verdict,
                        "reason": combined_council_reason,
                        "son_promoted": paused_pm,
                        "father_dominated": False,
                        "spirit_dominated": False,
                        "consensus_weights": (
                            {"father": 0.0, "son": 1.0, "spirit": 0.0}
                            if paused_pm
                            else {"father": 1/3, "son": 1/3, "spirit": 1/3}
                        ),
                        "primary_dimension": "combined LLM self-fused",
                        "_parse_error": None,
                    }, mode_id=mode_name)
                    # v8.14 N4 (P1 fixed) — Module N alignment resonance per mode (combined).
                    # Spirit metadata not parsed in combined → assume "NONE"
                    # (combined has no rescan loop, so this is consistent).
                    # Reads from parsed Stage 3 filter dict directly.
                    eight_law_scores_c = console._parse_eight_law_scores(stage3)
                    alignment_pm = console._detect_alignment_resonance(
                        eight_law_scores_c,
                        son_veto_type=son_meta_pm.get("veto_type"),
                        spirit_trigger_mode="NONE",
                        user_query=req.input,
                    )
                    if alignment_pm:
                        yield emit_c("alignment_resonance", alignment_pm, mode_id=mode_name)
                    combined_veto_status[mode_name]["alignment_resonance"] = alignment_pm
                    if paused_pm:
                        # Override FATHER section to paused chip
                        yield emit_c("father_paused", {
                            "veto_type": son_meta_pm["veto_type"],
                            "authentic_suffering_score": son_meta_pm["authentic_suffering_score"],
                            "primary_pain_locus": son_meta_pm["primary_pain_locus"],
                            "physical_cost_present": son_meta_pm["physical_cost_present"],
                            "reason": son_meta_pm["veto_type"],
                        }, mode_id=mode_name)
                        # Also emit non-father roles normally
                        for role in ("son", "spirit", "council"):
                            yield emit_c("node", {
                                "role": role,
                                "output": section.get(role, ""),
                            }, mode_id=mode_name)
                    else:
                        for role in ("father", "son", "spirit", "council"):
                            yield emit_c("node", {
                                "role": role,
                                "output": section.get(role, ""),
                            }, mode_id=mode_name)

            # Output self-audit + done (single unified audit for combined)
            full_result = {
                "input": req.input, "effective_input": req.input,
                "stage1": stage1, "stage2": stage2, "stage3": stage3,
                "dispatch": {"mode": "combined", "references": [],
                             "mode_rationale": f"combined({','.join(mode_names)})"},
                "all_data_refs": [],
                "selected_modes": mode_names,
                "execution_strategy": "combined",
                "combined_output_raw": combined_output,
                "parsed_modes": parsed,
                "father": "\n\n".join([f"## {m}\n{parsed.get(m,{}).get('father','')}" for m in mode_names]),
                "son":    "\n\n".join([f"## {m}\n{parsed.get(m,{}).get('son','')}"    for m in mode_names]),
                "spirit": "\n\n".join([f"## {m}\n{parsed.get(m,{}).get('spirit','')}" for m in mode_names]),
                "council":"\n\n".join([f"## {m}\n{parsed.get(m,{}).get('council','')}"for m in mode_names]),
                "timestamp": datetime.now().isoformat(),
                "node_config": {r: f"{c.provider}/{c.model}" for r, c in console.nodes.items()},
                "exit_path": "combined",
                "pipeline_mode": "combined",
                "inference_usage": inference_snapshot(),
                # v8.9 Phase A10 — combined LLM self-fuses; no Python 4c fusion.
                "council_decision": {
                    "verdict": "consensus",
                    "reason": "combined_meta_call",
                    "consensus_weights": {"father": 1/3, "son": 1/3, "spirit": 1/3},
                    "primary_dimension": "combined LLM self-fused",
                },
                "council_fusion_deterministic": False,
                # v8.11 P6 — in-session conversation history
                "in_session_history": [t.model_dump() if hasattr(t, "model_dump") else t
                                       for t in (req.in_session_history or [])],
            }
            audit_dict = console.run_output_density_audit(full_result)
            full_result["output_density_audit"] = audit_dict
            full_result["density_audit"] = audit_dict
            _combined_usage = inference_snapshot()
            full_result["inference_usage"] = _combined_usage
            full_result["cost_metrics"] = {
                "route_kind": "combined",
                "estimated_model_calls": _combined_inference_policy.planned_calls,
                "model_call_budget": _combined_inference_policy.hard_max_calls,
                "actual_model_requests": _combined_usage.get("actual_requests", 0),
                "successful_model_requests": _combined_usage.get("successful_requests", 0),
                "failed_model_requests": _combined_usage.get("failed_requests", 0),
                "unique_model_count": _combined_usage.get("unique_model_count", 0),
            }
            yield emit_c("status", {"phase": "output_self_audit", "message": "系統輸出自查中..."})
            yield emit_c("density_audit", audit_dict)
            # v8.37 — physics_compute (combined-mode path)
            try:
                from services.physics_compute import to_event_payload as _phys_payload2
                _phys_data = _phys_payload2(
                    full_result.get("input", "") or "",
                    full_result.get("council", "") or full_result.get("father", "") or "",
                )
            except Exception as _e:
                _phys_data = {"display_label": "物理計算 dev-only · 唔影響 LLM 判斷",
                              "metrics": [], "error": f"{type(_e).__name__}: {_e}"}
            yield emit_c("physics_compute", _phys_data)
            # v8.31 — System 1 auto-save (always). req.save only governs SSE event.
            kairos_path = console.save_kairos(full_result, req.label,
                                               overwrite_filename=req.resume_filename)
            if req.save:
                yield emit_c("saved", {"filename": kairos_path.name})
            yield emit_c("inference_usage", _combined_usage)
            yield emit_c("done", {
                "timestamp": full_result["timestamp"],
                "protocol_status": {
                    "output_audit": {
                        "ran": bool(audit_dict.get("audit_ran", False)),
                        "density": audit_dict.get("density"),
                        "candidate_count": audit_dict.get("candidate_count", 0),
                        "proposed_path": audit_dict.get("proposed_path"),
                        "target": audit_dict.get("audit_target", "system_output"),
                    },
                    "audit_ran": audit_dict.get("audit_ran", False),
                    "density": audit_dict.get("density"),
                    "candidate_count": audit_dict.get("candidate_count", 0),
                    "proposed_path": audit_dict.get("proposed_path"),
                    "sync_delta_path": audit_dict.get("sync_delta_path"),
                    "execution_strategy": "combined",
                    "parsed_modes": list(parsed.keys()),
                    "missing_modes": missing,
                    "inference": inference_snapshot(),
                },
            })
        except Exception as ex:
            yield emit_c("inference_usage", inference_snapshot())
            err = json.dumps({"message": f"combined: {ex}", "_mode_id": "_combined"}, ensure_ascii=False)
            yield f"event: error\ndata: {err}\n\n"
        finally:
            try:
                _LLM_OVERRIDE_CTX.reset(_combined_token)
            except Exception:
                pass
            try:
                reset_inference_session(_combined_inference_token)
            except Exception:
                pass
            console.end_pipeline()

    async def multi_mode_outer():
        """v8.8 — Top-level multi-mode dispatcher. Selects between:
        - 1 mode → run event_generator inline (no tabs, legacy mode_id="_default")
        - N modes parallel → spawn N concurrent event_generators, multiplex via Queue
        - N modes combined → R6 _run_combined() shared Stage 1-3 + single meta-LLM call
        """
        if len(selected_modes) == 1:
            async for chunk in event_generator("_default", selected_modes[0]):
                yield chunk
            return

        if strategy == "parallel":
            # v8.8 R8 — Pre-attach cross-session ONCE, share across all pipelines.
            # Avoids N duplicate banners + N redundant disk reads. Emit event with
            # mode_id="_global" so frontend renders the banner once (not per-tab).
            shared_historical_ctx = ""
            shared_attached_sessions: List = []
            try:
                cs_cfg = console.cross_session_cfg
                if cs_cfg.enabled and not req.detach_history:
                    shared_attached_sessions = console._load_recent_session_summaries(
                        cs_cfg.n_recent, cs_cfg.mode,
                    )
                    if shared_attached_sessions:
                        shared_historical_ctx = console._format_history_block(
                            shared_attached_sessions, cs_cfg.mode,
                        )
                        evt = json.dumps({
                            "n_sessions": len(shared_attached_sessions),
                            "mode": cs_cfg.mode,
                            "last_label": shared_attached_sessions[0].get("label"),
                            "last_timestamp": shared_attached_sessions[0].get("timestamp"),
                            "sessions": [
                                {"filename": s.get("filename"),
                                 "timestamp": s.get("timestamp"),
                                 "label": s.get("label"),
                                 "summary": s.get("summary", "")[:120]}
                                for s in shared_attached_sessions
                            ],
                            "_mode_id": "_global",
                        }, ensure_ascii=False)
                        yield f"event: cross_session_attached\ndata: {evt}\n\n"
            except Exception:
                # Cross-session is non-critical; failure shouldn't block pipelines
                shared_historical_ctx = ""
                shared_attached_sessions = []

            queue: asyncio.Queue = asyncio.Queue()
            sentinel = object()

            async def drain(sel: ModeSelection):
                try:
                    async for chunk in event_generator(
                        sel.mode, sel,
                        _shared_historical_ctx=shared_historical_ctx,
                        _shared_attached_sessions=shared_attached_sessions,
                    ):
                        await queue.put(chunk)
                except Exception as ex:
                    err_payload = json.dumps(
                        {"message": f"[{sel.mode}] {ex}", "_mode_id": sel.mode},
                        ensure_ascii=False,
                    )
                    await queue.put(f"event: error\ndata: {err_payload}\n\n")
                finally:
                    await queue.put((sentinel, sel.mode))

            tasks = [asyncio.create_task(drain(s)) for s in selected_modes]
            done_count = 0
            try:
                while done_count < len(selected_modes):
                    item = await queue.get()
                    if isinstance(item, tuple) and len(item) == 2 and item[0] is sentinel:
                        done_count += 1
                    else:
                        yield item
            finally:
                for t in tasks:
                    if not t.done():
                        t.cancel()
            return

        # strategy == "combined" — R6 implementation
        async for chunk in _run_combined():
            yield chunk

    return StreamingResponse(multi_mode_outer(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })




# ═══════════════════════════════════════════════════════════════
# File Service Endpoints (FT-1) — 3-tier customization UI
# ═══════════════════════════════════════════════════════════════

@app.get("/api/files/tree")
async def get_files_tree():
    """Return 4-tier file tree (canonical / prompts / personal / config)."""
    try:
        return fs.get_tree()
    except Exception as e:
        raise HTTPException(500, f"tree error: {e}")


@app.get("/api/files/read")
async def read_file_endpoint(path: str):
    """Read file content. Any layer is readable."""
    try:
        return fs.read_file(path)
    except PathRejected as e:
        raise HTTPException(400, f"path rejected: {e}")
    except FileNotFoundError as e:
        raise HTTPException(404, f"file not found: {e}")
    except FileServiceError as e:
        raise HTTPException(400, str(e))


@app.post("/api/files/write")
async def write_file_endpoint(req: FileWriteRequest):
    """Write file. Layer 1 (canonical) rejected with 403. Layer 2 audited."""
    try:
        return fs.write_file(req.path, req.content)
    except PathRejected as e:
        raise HTTPException(400, f"path rejected: {e}")
    except PermissionError as e:
        raise HTTPException(403, f"read-only: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileServiceError as e:
        raise HTTPException(400, str(e))


@app.get("/api/files/diff")
async def diff_file_endpoint(path: str, version: Optional[str] = None):
    """Diff current file vs most-recent backup snapshot."""
    try:
        return fs.diff_file(path, version)
    except PathRejected as e:
        raise HTTPException(400, f"path rejected: {e}")
    except FileNotFoundError as e:
        raise HTTPException(404, f"file not found: {e}")
    except FileServiceError as e:
        raise HTTPException(400, str(e))




# ═══════════════════════════════════════════════════════════════
# Phase 1 Tool Endpoints — Browser + Calendar
# ═══════════════════════════════════════════════════════════════

@app.get("/api/tools/web_search")
async def tool_web_search(q: str, n: int = 5):
    """DuckDuckGo HTML scrape. Returns list of {title, url, snippet}."""
    try:
        return await browser.web_search(q, n)
    except BrowserServiceError as e:
        raise HTTPException(502, f"search failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"unexpected: {e}")


@app.get("/api/tools/fetch_url")
async def tool_fetch_url(url: str):
    """Fetch URL with SSRF protection + 5MB cap."""
    try:
        return await browser.fetch_url(url)
    except URLRejected as e:
        raise HTTPException(400, f"url rejected: {e}")
    except BrowserServiceError as e:
        raise HTTPException(502, f"fetch failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"unexpected: {e}")


@app.get("/api/tools/calendar/files")
async def tool_cal_files():
    """List .ics files in data/calendar/."""
    try:
        return calendar_svc.list_files()
    except Exception as e:
        raise HTTPException(500, f"calendar list failed: {e}")


@app.get("/api/tools/calendar/events")
async def tool_cal_events(
    file: str,
    from_dt: Optional[str] = None,
    to_dt: Optional[str] = None,
    limit: int = 50,
):
    """Parse .ics file, return events filtered by date range (YYYY-MM-DD)."""
    try:
        return calendar_svc.list_events(file, from_dt, to_dt, limit)
    except FileNotFoundError as e:
        raise HTTPException(404, f"calendar file not found: {e}")
    except CalendarServiceError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"calendar parse failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# Phase 3 Fix-3: LLM Provider Settings (Chat-UI exposed nodes.yaml)
# ═══════════════════════════════════════════════════════════════════

# Provider catalogue (default api_base + key env). Order = UI display order.
PROVIDERS_CATALOGUE = [
    {"name": "gemini",       "default_base": "https://generativelanguage.googleapis.com/v1beta/openai", "default_key_env": "GEMINI_API_KEY"},
    {"name": "openrouter",   "default_base": "https://openrouter.ai/api/v1",                            "default_key_env": "OPENROUTER_API_KEY"},
    {"name": "openai",       "default_base": "https://api.openai.com/v1",                               "default_key_env": "OPENAI_API_KEY"},
    {"name": "anthropic",    "default_base": "https://api.anthropic.com/v1",                            "default_key_env": "ANTHROPIC_API_KEY"},
    {"name": "groq",         "default_base": "https://api.groq.com/openai/v1",                          "default_key_env": "GROQ_API_KEY"},
    {"name": "cerebras",     "default_base": "https://api.cerebras.ai/v1",                              "default_key_env": "CEREBRAS_API_KEY"},
    {"name": "xai",          "default_base": "https://api.x.ai/v1",                                     "default_key_env": "XAI_API_KEY"},
    {"name": "ollama",       "default_base": "http://localhost:11434",                                  "default_key_env": ""},
    # v8.3 free-tier additions — all OpenAI-compatible
    {"name": "nvidia",       "default_base": "https://integrate.api.nvidia.com/v1",                     "default_key_env": "NVIDIA_API_KEY"},
    {"name": "sambanova",    "default_base": "https://api.sambanova.ai/v1",                             "default_key_env": "SAMBANOVA_API_KEY"},
    {"name": "cloudflare",   "default_base": "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1", "default_key_env": "CLOUDFLARE_AI_KEY"},
    {"name": "chutes",       "default_base": "https://llm.chutes.ai/v1",                                "default_key_env": "CHUTES_API_KEY"},
    {"name": "hyperbolic",   "default_base": "https://api.hyperbolic.xyz/v1",                           "default_key_env": "HYPERBOLIC_API_KEY"},
    {"name": "pollinations", "default_base": "https://text.pollinations.ai/openai",                     "default_key_env": ""},
    {"name": "codex_desktop",   "default_base": "app://codex",                                          "default_key_env": ""},
    {"name": "claude_desktop",  "default_base": "app://claude",                                         "default_key_env": ""},
    {"name": "chatgpt_desktop", "default_base": "app://chatgpt",                                        "default_key_env": ""},
    {"name": "copilot_desktop", "default_base": "app://copilot",                                        "default_key_env": ""},
    {"name": "grok_web",        "default_base": "https://grok.com",                                     "default_key_env": ""},
    {"name": "gemini_web",      "default_base": "https://gemini.google.com",                            "default_key_env": ""},
]

NODE_ROLES = ["delabeling", "explanation", "filter", "dispatcher", "father", "son", "spirit", "council"]

# Named presets — operator quick-switch buttons in Settings modal
PRESETS = [
    {
        "id": "gemini_direct",
        "name": "📡 Gemini Direct (fast, cap 15 RPM)",
        "description": "全 8 nodes Gemini 2.5 Flash. 速度最快但每分鐘 15 turn cap，daily 1500 turns.",
        "config": {
            role: {
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
                "api_key_env": "GEMINI_API_KEY",
                "temperature": 0.5,
                "max_tokens": 2000,
            }
            for role in NODE_ROLES
        },
    },
    {
        "id": "openrouter_free",
        "name": "🌐 OpenRouter Free (slow, generous quota)",
        "description": "全 8 nodes OpenRouter free tier. 慢但 quota 充裕，撞 Gemini 429 嘅 fallback.",
        "config": {
            role: {
                "provider": "openrouter",
                "model": "openai/gpt-oss-120b:free",
                "api_base": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "temperature": 0.5,
                "max_tokens": 2000,
            }
            for role in NODE_ROLES
        },
    },
    {
        "id": "mixed_e5",
        "name": "🔀 Mixed Cross-Family (Plan E-5, current default)",
        "description": "7 nodes Gemini direct + Council 用 OpenRouter gpt-oss-120b (cross-family 整合).",
        "config": {
            **{
                role: {
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "api_key_env": "GEMINI_API_KEY",
                    "temperature": 0.5,
                    "max_tokens": 2000,
                }
                for role in NODE_ROLES if role != "council"
            },
            "council": {
                "provider": "openrouter",
                "model": "openai/gpt-oss-120b:free",
                "api_base": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "temperature": 0.5,
                "max_tokens": 2500,
            },
        },
    },
    {
        "id": "ollama_local",
        "name": "💻 Local Ollama (offline, free)",
        "description": "全 8 nodes 本地 Ollama. 需要 `ollama pull qwen2.5:3b` 先 work.",
        "config": {
            role: {
                "provider": "ollama",
                "model": "qwen2.5:3b",
                "api_base": "http://localhost:11434",
                "api_key_env": "",
                "temperature": 0.5,
                "max_tokens": 2000,
            }
            for role in NODE_ROLES
        },
    },
]


class NodeUpdateSpec(BaseModel):
    provider: str
    model: str
    api_base: Optional[str] = ""
    api_key_env: Optional[str] = ""
    temperature: float = 0.5
    max_tokens: int = 2000


class NodesConfigUpdate(BaseModel):
    nodes: dict  # role -> NodeUpdateSpec dict
    # v8.2 +failover: optional — when present, replaces saved profiles/chain/cooldown
    api_profiles: Optional[dict] = None
    task_profiles: Optional[dict] = None      # lightweight routing profiles
    failover: Optional[dict] = None
    per_node_fallback: Optional[dict] = None   # role -> list[profile_name]
    # v8.4 — cross-session memory toggle
    cross_session: Optional[dict] = None       # {enabled, n_recent, mode}


# Default profiles seeded when nodes.yaml has no `api_profiles` section yet.
DEFAULT_API_PROFILES = {
    "openrouter_free": {
        "provider": "openrouter",
        "api_base": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "openai/gpt-oss-120b:free",
        "enabled": True,
    },
    "gemini_flash": {
        "provider": "gemini",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
        "enabled": True,
    },
    "groq_llama": {
        "provider": "groq",
        "api_base": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "enabled": True,
    },
    "cerebras_llama": {
        "provider": "cerebras",
        "api_base": "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        # Updated 2026-05-17: prior `llama3.3-70b` returned 404 from Cerebras.
        # Operator's Cerebras dashboard only exposes `llama3.1-8b` on free tier.
        "default_model": "llama3.1-8b",
        "enabled": True,
    },
    # v8.3 — disabled by default; user fills env var + flips `enabled` in UI to activate.
    "nvidia_nim": {
        "provider": "nvidia",
        "api_base": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "default_model": "deepseek-ai/deepseek-r1",
        "enabled": False,
    },
    "sambanova": {
        "provider": "sambanova",
        "api_base": "https://api.sambanova.ai/v1",
        "api_key_env": "SAMBANOVA_API_KEY",
        "default_model": "Meta-Llama-3.1-405B-Instruct",
        "enabled": False,
    },
    "cloudflare_ai": {
        "provider": "cloudflare",
        "api_base": "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        "api_key_env": "CLOUDFLARE_AI_KEY",
        "default_model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "enabled": False,
    },
    "chutes_ai": {
        "provider": "chutes",
        "api_base": "https://llm.chutes.ai/v1",
        "api_key_env": "CHUTES_API_KEY",
        "default_model": "deepseek-ai/DeepSeek-R1",
        "enabled": False,
    },
    "hyperbolic": {
        "provider": "hyperbolic",
        "api_base": "https://api.hyperbolic.xyz/v1",
        "api_key_env": "HYPERBOLIC_API_KEY",
        "default_model": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "enabled": False,
    },
    "pollinations": {
        "provider": "pollinations",
        "api_base": "https://text.pollinations.ai/openai",
        "api_key_env": "",
        "default_model": "openai",
        "enabled": False,        # per-IP rate; default off to avoid accidental rate-lock
    },
    "codex_desktop": {
        "provider": "codex_desktop",
        "api_base": "app://codex",
        "api_key_env": "",
        "default_model": "codex",
        "enabled": True,
    },
    "claude_desktop": {
        "provider": "claude_desktop",
        "api_base": "app://claude",
        "api_key_env": "",
        "default_model": "claude_desktop",
        "enabled": False,
    },
    "chatgpt_desktop": {
        "provider": "chatgpt_desktop",
        "api_base": "app://chatgpt",
        "api_key_env": "",
        "default_model": "chatgpt",
        "enabled": False,
    },
    "copilot_desktop": {
        "provider": "copilot_desktop",
        "api_base": "app://copilot",
        "api_key_env": "",
        "default_model": "copilot",
        "enabled": False,
    },
    "xai_grok3": {
        "provider": "xai",
        "api_base": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "default_model": "grok-3",
        "enabled": False,
    },
    "xai_grok3_mini": {
        "provider": "xai",
        "api_base": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "default_model": "grok-3-mini",
        "enabled": False,
    },
    "gemini_25_pro": {
        "provider": "gemini",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-pro",
        "enabled": False,
    },
    "gemini_25_flash": {
        "provider": "gemini",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
        "enabled": False,
    },
    "grok_web": {
        "provider": "grok_web",
        "api_base": "https://grok.com",
        "api_key_env": "",
        "default_model": "grok_web",
        "enabled": False,
    },
    "gemini_web": {
        "provider": "gemini_web",
        "api_base": "https://gemini.google.com",
        "api_key_env": "",
        "default_model": "gemini_web",
        "enabled": False,
    },
}


@app.get("/api/nodes/config")
async def get_nodes_config():
    """Return current 8 nodes + providers catalogue + presets + key status +
    api_profiles + failover config + per-node fallback overrides + active health.

    ⚠ NEVER return API key values. Only env var names + boolean "is set".
    """
    nodes_out = {}
    for role in NODE_ROLES:
        cfg = console.nodes.get(role)
        if cfg is None:
            nodes_out[role] = None
            continue
        nodes_out[role] = {
            "provider": cfg.provider,
            "model": cfg.model,
            "api_base": cfg.api_base or "",
            "api_key_env": cfg.api_key_env or "",
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "fallback": console.node_fallbacks.get(role, []),
        }

    from services.task_profiles import load_task_profiles as _load_task_profiles
    task_profiles_out = _load_task_profiles(CONFIG_DIR)

    # Key status: collect all api_key_env names from current config + provider catalogue defaults
    all_key_envs = set()
    for spec in nodes_out.values():
        if spec and spec.get("api_key_env"):
            all_key_envs.add(spec["api_key_env"])
    for prov in PROVIDERS_CATALOGUE:
        if prov.get("default_key_env"):
            all_key_envs.add(prov["default_key_env"])
    # Also include keys referenced by api_profiles
    for p in console.failover_cfg.profiles.values():
        if p.api_key_env:
            all_key_envs.add(p.api_key_env)
    for p in task_profiles_out.values():
        if p.get("api_key_env"):
            all_key_envs.add(p["api_key_env"])
    key_status = {k: bool(os.environ.get(k)) for k in sorted(all_key_envs)}

    # Serialize api_profiles (incl. v8.3 `enabled` flag).
    profiles_out = {
        name: {
            "provider": p.provider,
            "api_base": p.api_base or "",
            "api_key_env": p.api_key_env or "",
            "default_model": p.default_model or "",
            "enabled": getattr(p, "enabled", True),
        }
        for name, p in console.failover_cfg.profiles.items()
    }
    # v8.3: merge built-in defaults for any profile name not yet in user's yaml,
    # so the Settings UI surfaces all known free-tier providers as soon as the
    # operator opens the modal. Defaults are merged with enabled=False so they
    # don't perturb existing failover chain until operator explicitly opts in.
    for name, default_spec in DEFAULT_API_PROFILES.items():
        if name not in profiles_out:
            profiles_out[name] = {
                "provider": default_spec.get("provider", ""),
                "api_base": default_spec.get("api_base", ""),
                "api_key_env": default_spec.get("api_key_env", ""),
                "default_model": default_spec.get("default_model", ""),
                "enabled": False,    # opt-in by operator, not auto-active
            }

    return {
        "nodes": nodes_out,
        "providers": PROVIDERS_CATALOGUE,
        "presets": PRESETS,
        "api_key_status": key_status,
        "pipeline_running": console.is_pipeline_running(),
        "api_profiles": profiles_out,
        "task_profiles": task_profiles_out,
        "failover": {
            "enabled": console.failover_cfg.enabled,
            "global_chain": console.failover_cfg.global_chain,
            "cooldown_seconds": console.failover_cfg.cooldown_seconds,
            "trigger_on": console.failover_cfg.trigger_on,
        },
        "cross_session": {
            "enabled": console.cross_session_cfg.enabled,
            "n_recent": console.cross_session_cfg.n_recent,
            "mode": console.cross_session_cfg.mode,
        },
        "health": console.health.snapshot(),
        "health_persistence": console.health.persistence_status(),
        "adaptive_routing": console.adaptive_failover_summary(),
        "active": console.active_profile_summary(),
    }


@app.get("/api/nodes/health")
async def get_nodes_health():
    from services.provider_rate_limiter import provider_rate_limiter
    """Lightweight poll endpoint — toolbar pill + health panel call this every 2s."""
    return {
        "health": console.health.snapshot(),
        "provider_queue": provider_rate_limiter.snapshot(),
        "persistence": console.health.persistence_status(),
        "adaptive_routing": console.adaptive_failover_summary(),
        "active": console.active_profile_summary(),
        "pipeline_running": console.is_pipeline_running(),
    }


class HealthResetRequest(BaseModel):
    profile: Optional[str] = None   # if omitted, reset all
    force: bool = False


@app.post("/api/nodes/health/reset")
async def reset_nodes_health(body: HealthResetRequest):
    from services.provider_rate_limiter import provider_rate_limiter

    snapshot = console.health.snapshot()
    names = [body.profile] if body.profile else list(snapshot)
    protected = [
        {
            "profile": name,
            "trigger": (snapshot.get(name) or {}).get("last_trigger"),
            "cooldown_remaining_s": (snapshot.get(name) or {}).get("cooldown_remaining_s", 0),
        }
        for name in names
        if (snapshot.get(name) or {}).get("cooling")
        and (snapshot.get(name) or {}).get("last_trigger") in {"http_429", "quota"}
    ]
    if protected and not body.force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "rate_limit_cooldown_protected",
                "message": "429／quota 冷卻仍然生效；一般健康重設不會強行重試。",
                "profiles": protected,
            },
        )
    """Clear cooldown / counts for one profile, or all profiles."""
    if body.profile:
        console.health.clear_cooldown(body.profile)
        if body.force:
            profile = console.failover_cfg.profiles.get(body.profile)
            if profile:
                provider_rate_limiter.clear(profile.provider)
        return {"cleared": body.profile, "forced": body.force}
    console.health.reset()
    if body.force:
        provider_rate_limiter.clear()
    return {"cleared": "all", "forced": body.force}


def _validate_nodes_payload(payload: dict) -> Optional[str]:
    """Validate posted nodes config. Returns error string or None."""
    if not isinstance(payload, dict):
        return "nodes payload must be dict"
    valid_providers = {p["name"] for p in PROVIDERS_CATALOGUE}
    missing_roles = set(NODE_ROLES) - set(payload.keys())
    if missing_roles:
        return f"missing roles: {sorted(missing_roles)}"
    for role, spec in payload.items():
        if role not in NODE_ROLES:
            return f"unknown role: {role}"
        if not isinstance(spec, dict):
            return f"role {role}: spec must be dict"
        prov = spec.get("provider", "").strip()
        if prov not in valid_providers:
            return f"role {role}: invalid provider {prov!r} (must be one of {sorted(valid_providers)})"
        model = spec.get("model", "").strip()
        if not model or len(model) > 200:
            return f"role {role}: model name empty or too long"
        api_base = (spec.get("api_base") or "").strip()
        if api_base and not (api_base.startswith("http://") or api_base.startswith("https://")):
            return f"role {role}: api_base must start with http:// or https://"
        if len(api_base) > 500:
            return f"role {role}: api_base too long"
        key_env = (spec.get("api_key_env") or "").strip()
        if key_env and not key_env.replace("_", "").isalnum():
            return f"role {role}: api_key_env must be alnum/underscore only"
        try:
            temp = float(spec.get("temperature", 0.5))
        except (TypeError, ValueError):
            return f"role {role}: temperature must be number"
        if not (0.0 <= temp <= 2.0):
            return f"role {role}: temperature out of range [0.0, 2.0]"
        try:
            mt = int(spec.get("max_tokens", 2000))
        except (TypeError, ValueError):
            return f"role {role}: max_tokens must be int"
        if not (50 <= mt <= 32000):
            return f"role {role}: max_tokens out of range [50, 32000]"
    return None


def _validate_cross_session(cs: Optional[dict]) -> Optional[str]:
    """v8.4 — validate cross_session sub-payload."""
    if cs is None:
        return None
    if not isinstance(cs, dict):
        return "cross_session must be dict"
    if "enabled" in cs and not isinstance(cs.get("enabled"), bool):
        return "cross_session.enabled must be boolean"
    if "n_recent" in cs:
        try:
            n = int(cs.get("n_recent"))
        except (TypeError, ValueError):
            return "cross_session.n_recent must be int"
        if not (1 <= n <= 10):
            return "cross_session.n_recent out of range [1, 10]"
    if "mode" in cs and cs.get("mode") not in ("summary", "full", "both"):
        return "cross_session.mode must be summary | full | both"
    return None


def _validate_failover_payload(profiles: Optional[dict], failover: Optional[dict],
                                per_node: Optional[dict]) -> Optional[str]:
    """Validate optional api_profiles / failover / per_node_fallback sections."""
    valid_providers = {p["name"] for p in PROVIDERS_CATALOGUE}
    profile_names: set = set()
    if profiles is not None:
        if not isinstance(profiles, dict):
            return "api_profiles must be dict"
        for name, p in profiles.items():
            if not isinstance(name, str) or not name.replace("_", "").replace("-", "").isalnum():
                return f"profile name {name!r}: alnum/underscore/dash only"
            if len(name) > 64:
                return f"profile name {name!r}: too long"
            if not isinstance(p, dict):
                return f"profile {name}: spec must be dict"
            prov = (p.get("provider") or "").strip()
            if prov and prov not in valid_providers:
                return f"profile {name}: invalid provider {prov!r}"
            api_base = (p.get("api_base") or "").strip()
            if api_base and not (
                api_base.startswith("http://")
                or api_base.startswith("https://")
                or api_base.startswith("app://")
            ):
                return f"profile {name}: api_base must start with http://, https://, or app://"
            key_env = (p.get("api_key_env") or "").strip()
            if key_env and not key_env.replace("_", "").isalnum():
                return f"profile {name}: api_key_env must be alnum/underscore only"
            if "enabled" in p and not isinstance(p.get("enabled"), bool):
                return f"profile {name}: enabled must be boolean"
            profile_names.add(name)

    if failover is not None:
        if not isinstance(failover, dict):
            return "failover must be dict"
        chain = failover.get("global_chain") or []
        if not isinstance(chain, list):
            return "failover.global_chain must be list"
        for n in chain:
            if not isinstance(n, str):
                return f"failover.global_chain entry not string: {n!r}"
            if profile_names and n not in profile_names:
                return f"failover.global_chain references unknown profile: {n}"
        try:
            cd = float(failover.get("cooldown_seconds", 300))
        except (TypeError, ValueError):
            return "failover.cooldown_seconds must be number"
        if not (5 <= cd <= 3600):
            return "failover.cooldown_seconds out of range [5, 3600]"

    if per_node is not None:
        if not isinstance(per_node, dict):
            return "per_node_fallback must be dict"
        for role, names in per_node.items():
            if role not in NODE_ROLES:
                return f"per_node_fallback: unknown role {role}"
            if not isinstance(names, list):
                return f"per_node_fallback[{role}] must be list"
            for n in names:
                if not isinstance(n, str):
                    return f"per_node_fallback[{role}] entry not string: {n!r}"
                if profile_names and n not in profile_names:
                    return f"per_node_fallback[{role}] references unknown profile: {n}"
    return None


@app.post("/api/nodes/config")
async def save_nodes_config(body: NodesConfigUpdate):
    """Validate posted config → write nodes.yaml atomically → reload in-place.

    Persists `nodes`, plus optional `api_profiles`, `failover`, and per-node
    `fallback:` overrides. If profiles/failover sections are omitted, preserves
    whatever is currently loaded.

    Refuses if pipeline running (HTTP 409).
    """
    import yaml as _yaml
    if console.is_pipeline_running():
        raise HTTPException(409, "Pipeline running. Wait for current turn then retry.")
    err = _validate_nodes_payload(body.nodes)
    if err:
        raise HTTPException(400, f"validation: {err}")
    err = _validate_failover_payload(body.api_profiles, body.failover, body.per_node_fallback)
    if err:
        raise HTTPException(400, f"failover validation: {err}")
    from services.task_profiles import (
        load_task_profiles as _load_task_profiles,
        merge_task_profiles as _merge_task_profiles,
        validate_task_profiles_payload as _validate_task_profiles_payload,
    )
    err = _validate_task_profiles_payload(
        body.task_profiles,
        valid_providers={p["name"] for p in PROVIDERS_CATALOGUE},
    )
    if err:
        raise HTTPException(400, f"task_profiles validation: {err}")
    err = _validate_cross_session(body.cross_session)
    if err:
        raise HTTPException(400, f"cross_session validation: {err}")

    # Resolve sections — if omitted, fall back to current console state.
    if body.api_profiles is not None:
        profiles_to_save = body.api_profiles
    else:
        profiles_to_save = {
            name: {
                "provider": p.provider,
                "api_base": p.api_base,
                "api_key_env": p.api_key_env,
                "default_model": p.default_model,
            }
            for name, p in console.failover_cfg.profiles.items()
        }
        # First-run bootstrap: seed defaults if yaml has no profiles yet
        if not profiles_to_save:
            profiles_to_save = dict(DEFAULT_API_PROFILES)

    if body.failover is not None:
        fo_to_save = body.failover
    else:
        fo_to_save = {
            "enabled": console.failover_cfg.enabled,
            "cooldown_seconds": console.failover_cfg.cooldown_seconds,
            "global_chain": console.failover_cfg.global_chain,
            "trigger_on": console.failover_cfg.trigger_on,
        }

    per_node_save = body.per_node_fallback if body.per_node_fallback is not None else console.node_fallbacks
    task_profiles_to_save = (
        body.task_profiles
        if body.task_profiles is not None
        else _load_task_profiles(CONFIG_DIR)
    )

    # v8.4 — cross_session save (preserve current state if omitted)
    if body.cross_session is not None:
        cs_to_save = body.cross_session
    else:
        cs_to_save = {
            "enabled": console.cross_session_cfg.enabled,
            "n_recent": console.cross_session_cfg.n_recent,
            "mode": console.cross_session_cfg.mode,
        }

    # Atomic write: tmp file + os.replace
    cfg_path = CONFIG_DIR / "nodes.yaml"
    tmp_path = cfg_path.with_suffix(".yaml.tmp")
    yaml_root: dict = {}

    # api_profiles (incl. v8.3 `enabled` flag — preserved even when False)
    cleaned_profiles = {}
    for name, p in profiles_to_save.items():
        if not isinstance(p, dict):
            continue
        spec = {
            "provider": (p.get("provider") or "").strip() or None,
            "api_base": (p.get("api_base") or "").strip() or None,
            "api_key_env": (p.get("api_key_env") or "").strip() or None,
            "default_model": (p.get("default_model") or p.get("model") or "").strip() or None,
        }
        cleaned = {k: v for k, v in spec.items() if v is not None}
        # Persist `enabled` only when explicitly False — backward compat:
        # missing field on read means True (see ApiProfile post_init).
        if p.get("enabled") is False:
            cleaned["enabled"] = False
        cleaned_profiles[name] = cleaned
    yaml_root["api_profiles"] = cleaned_profiles
    yaml_root["task_profiles"] = _merge_task_profiles(task_profiles_to_save)

    # failover
    yaml_root["failover"] = {
        "enabled": bool(fo_to_save.get("enabled", True)),
        "cooldown_seconds": float(fo_to_save.get("cooldown_seconds", 300)),
        "global_chain": list(fo_to_save.get("global_chain") or []),
        "trigger_on": list(fo_to_save.get("trigger_on") or [
            "http_429", "http_5xx", "quota", "timeout", "network", "profile_misconfig",
        ]),
    }

    # v8.4 cross_session
    yaml_root["cross_session"] = {
        "enabled": bool(cs_to_save.get("enabled", True)),
        "n_recent": int(cs_to_save.get("n_recent", 3)),
        "mode": str(cs_to_save.get("mode", "summary")),
    }

    # nodes
    yaml_root["nodes"] = {}
    for role in NODE_ROLES:
        spec = body.nodes[role]
        node_yaml = {
            "provider": spec["provider"].strip(),
            "model": spec["model"].strip(),
            "api_base": (spec.get("api_base") or "").strip() or None,
            "api_key_env": (spec.get("api_key_env") or "").strip() or None,
            "temperature": float(spec["temperature"]),
            "max_tokens": int(spec["max_tokens"]),
        }
        node_yaml = {k: v for k, v in node_yaml.items() if v is not None}
        fallback_list = per_node_save.get(role) if isinstance(per_node_save, dict) else None
        if fallback_list:
            node_yaml["fallback"] = list(fallback_list)
        yaml_root["nodes"][role] = node_yaml

    try:
        tmp_path.write_text(
            "# URUK Trinity Console — nodes config (UI-generated)\n"
            "# Edit via Settings modal in chat UI (preferred) or this file (advanced).\n\n"
            + _yaml.safe_dump(yaml_root, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        os.replace(str(tmp_path), str(cfg_path))
    except Exception as e:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise HTTPException(500, f"write nodes.yaml fail: {type(e).__name__}: {e}")

    # In-place reload
    reload_result = console.reload_nodes()
    if not reload_result.get("reloaded"):
        return {
            "saved": True,
            "applied_immediately": False,
            "restart_needed": True,
            "reload_error": reload_result.get("error"),
            "hint": "yaml written but reload failed. Restart py app.py to apply.",
        }
    return {
        "saved": True,
        "applied_immediately": True,
        "restart_needed": False,
        "nodes_loaded": reload_result.get("nodes", []),
    }


@app.get("/api/skills/list")
async def list_skills_endpoint():
    """v8.2: List enabled skills — used by Stress modal to populate target dropdown."""
    from skill_registry import skill_registry
    return {"skills": skill_registry.list_skills(enabled_only=False)}


# ─────────────────────────────────────────────────────────────
# v8.15 MS-2 — Source Registry CRUD
# Overlay JSON at data/source_registry_overlay.json. Lookup order:
#   overlay > seed (KNOWN_COORDINATES in source_registry.py) > UNVERIFIED
# ─────────────────────────────────────────────────────────────

class SourceMappingPayload(BaseModel):
    domain: str
    coordinate: str
    rating: str   # VERIFIED / PROBABLE / INFERRED / UNVERIFIED


class SourceMappingUpdate(BaseModel):
    coordinate: Optional[str] = None
    rating: Optional[str] = None


class SourceImportPayload(BaseModel):
    version: Optional[str] = "1.0"
    domain_count: Optional[int] = 0
    mappings: Dict[str, Dict[str, str]] = {}
    replace: Optional[bool] = False


@app.get("/api/source_registry")
async def source_registry_list():
    return {
        "mappings": source_registry.list_mappings(include_origin=True),
        "ratings": ["VERIFIED", "PROBABLE", "INFERRED", "UNVERIFIED"],
    }


@app.post("/api/source_registry")
async def source_registry_add(body: SourceMappingPayload):
    ok = source_registry.add_mapping(body.domain, body.coordinate, body.rating)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="invalid_mapping (rating must be VERIFIED/PROBABLE/INFERRED/UNVERIFIED, fields non-empty)",
        )
    return {"ok": True, "domain": body.domain.lower().strip()}


@app.put("/api/source_registry/{domain}")
async def source_registry_update(domain: str, body: SourceMappingUpdate):
    ok = source_registry.update_mapping(domain, coordinate=body.coordinate, rating=body.rating)
    if not ok:
        raise HTTPException(status_code=404, detail="unknown_domain_or_invalid_rating")
    return {"ok": True, "domain": domain.lower().strip()}


@app.delete("/api/source_registry/{domain}")
async def source_registry_delete(domain: str):
    ok = source_registry.delete_mapping(domain)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="overlay_entry_not_found (seed entries are immutable; overlay them instead)",
        )
    return {"ok": True, "domain": domain.lower().strip()}


@app.get("/api/source_registry/export")
async def source_registry_export():
    return source_registry.export_json()


@app.post("/api/source_registry/import")
async def source_registry_import(body: SourceImportPayload):
    result = source_registry.import_json(
        {"version": body.version, "mappings": body.mappings},
        replace=bool(body.replace),
    )
    return result


@app.post("/api/source_registry/reset")
async def source_registry_reset():
    ok = source_registry.reset_overlay()
    return {"ok": ok, "remaining_count": len(source_registry._overlay)}


# v8.15 MS-1 — Available search engines (read-only; for Settings UI)
@app.get("/api/search_engines")
async def search_engines_list():
    from services.search_engines import list_available_engines
    return {
        "engines": list_available_engines(),
        "current": {
            "primary": browser_node.primary_engine_name,
            "fallback": browser_node.fallback_engine_names,
            "min_coordinate_diversity": browser_node.min_coordinate_diversity,
            "max_total_queries": browser_node.max_total_queries,
        },
    }


@app.get("/api/providers/models")
async def list_known_models(provider: Optional[str] = None):
    """v8.3: Return known-good model names per provider for combobox hint.

    If `provider` is given, returns models for that provider only.
    Otherwise returns the full map. Empty list when provider is unknown.
    Freeform input remains the source-of-truth in Settings UI — this is hint only.
    """
    from model_catalogue import KNOWN_MODELS, models_for
    if provider:
        return {"provider": provider, "models": models_for(provider)}
    return {"all": KNOWN_MODELS}


@app.get("/api/system/identity")
async def system_identity_endpoint():
    """Layer 1: return URUK system identity — purpose, version, capability coverage."""
    from services.system_identity import get_identity
    return get_identity().to_dict()


@app.get("/api/system/fidelity")
async def get_system_fidelity():
    """Layer 2: return protocol fidelity metrics computed from recent sessions."""
    from services.performance_reality import compute_protocol_fidelity, fidelity_delta, load_baselines
    snap = compute_protocol_fidelity()
    delta = fidelity_delta()
    baselines = load_baselines()
    return {
        "current": snap.to_dict(),
        "delta": delta,
        "has_baseline": "fidelity_baseline" in baselines,
    }


@app.get("/api/system/density-gaps")
async def get_density_gaps():
    """Layer 3: return §4.6 density-signal gaps from recent sessions and KAIROS_LOG."""
    from services.density_bridge import scan_density_gaps
    gaps = scan_density_gaps()
    return {
        "count": len(gaps),
        "gaps": [{"id": g.gap_id, "signal": g.signal_type, "priority": g.priority,
                  "description": g.description, "sessions": g.session_count} for g in gaps],
    }


@app.get("/api/simulation/clock")
async def get_clock_simulation(
    lie_cost: float = 5.85,
    speed: float = 0.3,
    window_end: int = 2035
):
    """Civilizational Clock simulator: run the 5 URUK equations with parameters."""
    from services.custom_tools.simulate_civilizational_clock import execute
    return execute({"lie_cost": lie_cost, "deployment_speed": speed,
                    "window_end": window_end, "historical_anchors": True})


@app.post("/api/simulation/coordinate-map")
async def render_coordinate_map_endpoint(body: dict = Body({})):
    """Render a 3D Plotly coordinate map from Trinity Stage 2/3 analysis output."""
    from services.custom_tools.render_coordinate_map import execute
    return execute(body)


@app.post("/api/nodes/reload")
async def reload_nodes_endpoint():
    """Force in-place reload of nodes.yaml (no write)."""
    if console.is_pipeline_running():
        raise HTTPException(409, "Pipeline running. Wait for current turn then retry.")
    result = console.reload_nodes()
    if not result.get("reloaded"):
        raise HTTPException(500, result.get("error") or "reload failed")
    return result


# ═══════════════════════════════════════════════════════════════════
# Phase 4: Stress test (UI-triggered)
# ═══════════════════════════════════════════════════════════════════

class StressRequest(BaseModel):
    role: str = "dispatcher"
    n: int = 5
    mode: str = "live"          # "live" or "mock_quota"
    concurrency: int = 3        # parallel in-flight requests
    prompt: str = "ping"        # short throwaway input
    # v8.5 — temporarily override HealthTracker.cooldown_seconds for THIS run.
    # Default 300s is too aggressive for burst tests; let stress runs use 5s
    # so chain candidates recover within the test window. Restored after run.
    cooldown_override_seconds: Optional[float] = None   # None = no override


@app.post("/api/stress/run")
async def stress_run(body: StressRequest):
    """Fire N short requests at one node to surface which API hits quota first
    and whether the failover chain triggers correctly.

    mode=mock_quota: inject a fake 429 on every primary call so each request
                     walks the chain. Verifies failover wiring without spending
                     real quota.
    mode=live:       send real requests; on real 429/quota, failover should
                     kick in transparently.
    """
    if body.role not in NODE_ROLES:
        raise HTTPException(400, f"unknown role: {body.role}")
    if not (1 <= body.n <= 50):
        raise HTTPException(400, "n out of range [1, 50]")
    if not (1 <= body.concurrency <= 10):
        raise HTTPException(400, "concurrency out of range [1, 10]")
    if body.mode not in ("live", "mock_quota"):
        raise HTTPException(400, "mode must be 'live' or 'mock_quota'")
    if body.cooldown_override_seconds is not None:
        if not (0 <= body.cooldown_override_seconds <= 600):
            raise HTTPException(400, "cooldown_override_seconds out of range [0, 600]")
    if console.is_pipeline_running():
        raise HTTPException(409, "Pipeline running. Wait for current turn then retry.")

    import httpx as _httpx
    import time as _time

    def _mock_429() -> Exception:
        """Build a httpx.HTTPStatusError with status 429 for failover injection."""
        req = _httpx.Request("POST", "https://mock/")
        resp = _httpx.Response(429, request=req, text="mock quota")
        return _httpx.HTTPStatusError("mock 429", request=req, response=resp)

    # v8.5 — temporarily override cooldown for this stress run
    saved_cooldown: Optional[float] = None
    if body.cooldown_override_seconds is not None:
        saved_cooldown = console.health.cooldown_seconds
        console.health.set_cooldown_seconds(body.cooldown_override_seconds)

    sem = asyncio.Semaphore(body.concurrency)
    results: List[dict] = []
    t_start = _time.time()

    async def _one(i: int):
        attempts: List[dict] = []
        async with sem:
            t0 = _time.time()
            ok = False
            err = None
            try:
                await console.call_node(
                    body.role,
                    user_input=body.prompt,
                    protocol_text="",
                    extra_context="",
                    attempts_out=attempts,
                    inject_error=_mock_429() if body.mode == "mock_quota" else None,
                )
                ok = True
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
            results.append({
                "i": i,
                "ok": ok,
                "elapsed_ms": round((_time.time() - t0) * 1000, 1),
                "error": err,
                "attempts": attempts,
            })

    try:
        await asyncio.gather(*(_one(i) for i in range(body.n)))
    finally:
        # v8.5 — always restore cooldown even if gather raises
        if saved_cooldown is not None:
            console.health.set_cooldown_seconds(saved_cooldown)

    total_ms = round((_time.time() - t_start) * 1000, 1)

    # Aggregate per-profile stats from attempts
    by_profile: Dict[str, dict] = {}
    for r in results:
        for a in r["attempts"]:
            prof = a.get("profile", "?")
            slot = by_profile.setdefault(prof, {"ok": 0, "fail": 0, "triggers": {}})
            if a.get("trigger") == "ok":
                slot["ok"] += 1
            else:
                slot["fail"] += 1
                t = a.get("trigger", "?")
                slot["triggers"][t] = slot["triggers"].get(t, 0) + 1

    return {
        "role": body.role,
        "mode": body.mode,
        "n": body.n,
        "concurrency": body.concurrency,
        "cooldown_override_seconds": body.cooldown_override_seconds,
        "cooldown_restored": saved_cooldown,
        "total_ms": total_ms,
        "success_count": sum(1 for r in results if r["ok"]),
        "fail_count": sum(1 for r in results if not r["ok"]),
        "by_profile": by_profile,
        "results": results,
        "health": console.health.snapshot(),
    }


# ─────────────────────────────────────────────────────────────────
# v8.42 — Planner-Executor Agent API
# POST /api/agent/run  → SSE stream of StepEvents
# POST /api/agent/plan → non-streaming: return plan JSON only (dry_run=True)
# ─────────────────────────────────────────────────────────────────

from planner_executor import PlannerExecutorPipeline, AgentConfig


class AgentRunRequest(BaseModel):
    """Body for /api/agent/run and /api/agent/plan."""
    intent: str                             # natural language user request
    dry_run: bool = False                   # True → plan only, no execution
    include_screenshot: bool = True         # pass current screen to Planner
    # Planner LLM (大模型)
    planner_model: str = "gemini-2.5-flash"
    planner_api_base: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    planner_provider: str = "gemini"
    planner_api_key: str = ""               # falls back to env vars
    # Executor LLMs (細模型 via Ollama)
    executor_text_model: str = ""
    executor_model: str = ""                # vision model
    executor_ollama_base: str = ""
    executor_resolve_all_steps: bool = True


@app.post("/api/agent/run")
async def agent_run(req: AgentRunRequest):
    """Stream Planner-Executor pipeline as SSE.

    Each event: event: agent\\ndata: <json>\\n\\n
    Event types: planning / plan / step_start / step_visual / step_visual_resolved
                 / step_done / step_approval_required / step_skipped
                 / step_error / error / done
    """
    from services.task_profiles import get_task_profile as _agent_profile
    _small_profile = _agent_profile("small", CONFIG_DIR)
    _vision_profile = _agent_profile("vision", CONFIG_DIR)
    cfg = AgentConfig(
        planner_model=req.planner_model,
        planner_api_base=req.planner_api_base,
        planner_provider=req.planner_provider,
        planner_api_key=req.planner_api_key,
        executor_text_model=req.executor_text_model or _small_profile.get("model", "qwen2.5:3b"),
        executor_model=req.executor_model or _vision_profile.get("model", "qwen3-vl:4b"),
        executor_ollama_base=(
            req.executor_ollama_base
            or _small_profile.get("api_base")
            or _vision_profile.get("api_base")
            or "http://localhost:11434"
        ),
        executor_resolve_all_steps=req.executor_resolve_all_steps,
        include_screenshot_in_plan=req.include_screenshot,
        dry_run=req.dry_run,
    )

    async def generator():
        pipeline = PlannerExecutorPipeline(cfg)
        try:
            async for event in pipeline.run(req.intent):
                yield event.to_sse()
        except Exception as e:
            import json as _json
            yield (
                f"event: agent\ndata: "
                f"{_json.dumps({'event_type': 'error', 'error': f'{type(e).__name__}: {e}'}, ensure_ascii=False)}"
                f"\n\n"
            )

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/agent/plan")
async def agent_plan(req: AgentRunRequest):
    """Non-streaming: return the Planner's JSON plan only (no execution).

    Useful for previewing what the agent would do before confirming execution.
    Always runs as dry_run=True regardless of req.dry_run.
    """
    from planner_executor import Planner
    import os as _os

    api_key = (req.planner_api_key
               or _os.environ.get("GEMINI_API_KEY", "")
               or _os.environ.get("OPENROUTER_API_KEY", "")
               or _os.environ.get("ANTHROPIC_API_KEY", ""))
    planner = Planner(
        model=req.planner_model,
        provider=req.planner_provider,
        api_base=req.planner_api_base,
        api_key=api_key,
    )
    try:
        plan = await planner.make_plan(
            req.intent,
            include_screenshot=req.include_screenshot,
        )
        return {
            "ok": True,
            "goal": plan.goal,
            "step_count": len(plan.steps),
            "planner_model": plan.planner_model,
            "planner_reasoning": plan.planner_reasoning,
            "steps": [s.to_dict() for s in plan.steps],
            "raw_json": plan.raw_json,
        }
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────
# v8.44 — Agent Tools Management API
# GET    /api/agent/tools           → list tools (overlay applied)
# PATCH  /api/agent/tool/{name}     → edit description / category
# POST   /api/agent/tool            → register custom tool
# DELETE /api/agent/tool/{name}     → disable (base) or remove (custom)
#
# Overlay persists to: data/agent_tools_overlay.json
# Base registry (computer_tools.py) is never mutated.
# ─────────────────────────────────────────────────────────────────

_TOOLS_OVERLAY_FILE = DATA_DIR / "agent_tools_overlay.json"

# ─────────────────────────────────────────────────────────────────
# v8.45 — Tool Workshop system prompt (injected as protocol_text)
# Used by pipeline_mode="tool_workshop" and the /tool_workshop chat mode.
# {{TOOLS_LIST}} is replaced at runtime with the current tool registry.
# ─────────────────────────────────────────────────────────────────
_TOOL_WORKSHOP_SYSTEM_PROMPT = """\
你係 URUK Tool Workshop 助手。你嘅職責：
1. 用廣東話解釋工具系統點工作、每個工具點用、點樣設計新工具
2. 當用戶想新增工具，生成完整 Python 實作並包裝入 <TOOL_INSTALL> 標籤

已登記嘅工具（{{TOOLS_LIST}}）

── 如果用戶只係問問題 ──
用廣東話清楚解釋，唔需要 <TOOL_INSTALL> 標籤。

── 如果用戶想新增工具 ──
先用廣東話確認你理解需求，然後生成工具。
在回應最後加入：

<TOOL_INSTALL>
{
  "name": "snake_case_name",
  "description": "廣東話描述：工具用途 + 返回值格式",
  "category": "screen|mouse|keyboard|file|state|clipboard|nav|wait|misc",
  "needs_visual": false,
  "args": [
    {"name": "arg", "type": "str|int|float|bool", "required": true, "default": null, "description": "用途"}
  ],
  "python_code": "def execute(args: dict) -> dict:\\n    try:\\n        # 實作\\n        return {...}\\n    except Exception as e:\\n        return {\\"error\\": str(e)}",
  "explanation": "brief English summary"
}
</TOOL_INSTALL>

python_code 規則：
- 函數簽名必須係：def execute(args: dict) -> dict
- 用 args.get("key", default) 提取參數
- 所有邏輯包喺 try/except 內，失敗返回 {"error": str(e)}
- 只用：os, sys, pathlib, json, subprocess, time, datetime, re, shutil, tempfile, csv, base64
- 可選（先 try import）：pyautogui, PIL, pyperclip
- 唔好 import ToolSpec / ArgSpec
- 返回 JSON-serializable dict

重要：python_code 入面嘅雙引號用 \\\" 轉義（因為整個 block 係 JSON string）。
如果唔確定需求，先問清楚再生成。
"""


def _load_tools_overlay() -> dict:
    if not _TOOLS_OVERLAY_FILE.exists():
        return {}
    try:
        with open(_TOOLS_OVERLAY_FILE, encoding="utf-8") as _f:
            return json.load(_f)
    except Exception:
        return {}


def _save_tools_overlay(overlay: dict) -> None:
    _TOOLS_OVERLAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_TOOLS_OVERLAY_FILE, "w", encoding="utf-8") as _f:
        json.dump(overlay, _f, ensure_ascii=False, indent=2)


def _get_merged_tools() -> list:
    """Merge base TOOL_REGISTRY with overlay (disabled, edits, custom tools)."""
    from services.computer_tools import TOOL_REGISTRY
    overlay = _load_tools_overlay()
    result = []
    for name, spec in TOOL_REGISTRY.items():
        d = spec.to_dict()
        d["custom"] = False
        ov = overlay.get(name, {})
        if ov.get("disabled"):
            continue
        if "description" in ov:
            d["description"] = ov["description"]
        if "category" in ov:
            d["category"] = ov["category"]
        if "needs_visual" in ov:
            d["needs_visual"] = ov["needs_visual"]
        result.append(d)
    # Append custom tools (not in base registry)
    for name, ov in overlay.items():
        if ov.get("custom") and not ov.get("disabled"):
            result.append({
                "name": name,
                "description": ov.get("description", ""),
                "args_schema": ov.get("args_schema", {"type": "object", "properties": {}, "required": []}),
                "needs_visual": ov.get("needs_visual", False),
                "category": ov.get("category", "misc"),
                "custom": True,
            })
    return result


class ToolPatchRequest(BaseModel):
    description: Optional[str] = None
    category: Optional[str] = None
    needs_visual: Optional[bool] = None


class ToolAddRequest(BaseModel):
    name: str
    description: str
    category: str = "misc"
    needs_visual: bool = False
    args_schema: Optional[dict] = None


@app.get("/api/agent/tools")
async def agent_tools():
    """List all tools with overlay applied."""
    tools = _get_merged_tools()
    return {"tools": tools, "tool_count": len(tools)}


@app.patch("/api/agent/tool/{name}")
async def patch_agent_tool(name: str, req: ToolPatchRequest):
    """Edit description / category of an existing tool."""
    overlay = _load_tools_overlay()
    entry = overlay.get(name, {})
    if req.description is not None:
        entry["description"] = req.description
    if req.category is not None:
        entry["category"] = req.category
    if req.needs_visual is not None:
        entry["needs_visual"] = req.needs_visual
    overlay[name] = entry
    _save_tools_overlay(overlay)
    return {"ok": True, "name": name}


@app.post("/api/agent/tool")
async def add_agent_tool(req: ToolAddRequest):
    """Register a new custom tool (description-only; Python impl separate)."""
    from services.computer_tools import TOOL_REGISTRY
    if req.name in TOOL_REGISTRY:
        raise HTTPException(400, f"Tool '{req.name}' already exists in base registry. Use PATCH to edit.")
    overlay = _load_tools_overlay()
    if req.name in overlay and not overlay[req.name].get("disabled"):
        raise HTTPException(400, f"Custom tool '{req.name}' already exists.")
    # Validate name: snake_case only
    if not req.name.replace("_", "").isalnum() or not req.name[0].isalpha():
        raise HTTPException(400, "Tool name must be snake_case (letters, digits, underscores; start with letter).")
    overlay[req.name] = {
        "custom": True,
        "description": req.description,
        "category": req.category,
        "needs_visual": req.needs_visual,
        "args_schema": req.args_schema or {"type": "object", "properties": {}, "required": []},
        "disabled": False,
    }
    _save_tools_overlay(overlay)
    return {"ok": True, "name": req.name}


@app.delete("/api/agent/tool/{name}")
async def delete_agent_tool(name: str):
    """Disable base tool or remove custom tool."""
    from services.computer_tools import TOOL_REGISTRY
    overlay = _load_tools_overlay()
    if name in TOOL_REGISTRY:
        entry = overlay.get(name, {})
        entry["disabled"] = True
        overlay[name] = entry
        _save_tools_overlay(overlay)
        return {"ok": True, "name": name, "action": "disabled"}
    elif name in overlay and overlay[name].get("custom"):
        del overlay[name]
        _save_tools_overlay(overlay)
        return {"ok": True, "name": name, "action": "removed"}
    else:
        raise HTTPException(404, f"Tool '{name}' not found.")


# ─────────────────────────────────────────────────────────────────
# v8.45 — AI Tool Designer
# POST /api/agent/tool/design   → LLM drafts spec + Python code
# POST /api/agent/tool/install  → validate + write + hot-reload
# POST /api/agent/tool/reload   → rescan custom_tools directory
# ─────────────────────────────────────────────────────────────────

_TOOL_DESIGNER_PROMPT = """\
You are a tool designer for the URUK Trinity Console desktop automation agent (Python 3.11+, Windows).
Given the user's intent, design ONE new Python tool.

Available tool categories: screen, mouse, keyboard, file, state, clipboard, nav, wait, misc
Available libraries (all stdlib unless noted):
  os, sys, pathlib, json, subprocess, time, datetime, re, shutil, tempfile, csv, base64, hashlib
  Optional (check at runtime if needed): pyautogui (desktop automation), PIL/Pillow (images), pyperclip (clipboard)

Output ONLY a single JSON object — no markdown fences, no explanation outside JSON:
{
  "name": "snake_case_name",
  "description": "廣東話描述：說明用途同返回值格式",
  "category": "screen|mouse|keyboard|file|state|clipboard|nav|wait|misc",
  "needs_visual": false,
  "args": [
    {"name": "arg_name", "type": "str|int|float|bool", "required": true, "default": null, "description": "arg purpose"}
  ],
  "python_code": "...",
  "explanation": "brief English summary"
}

Rules for python_code:
1. Signature MUST be: def execute(args: dict) -> dict
2. Extract args via: args.get("key", default)
3. Wrap ALL logic in try/except; return {"error": str(e)} on failure
4. Return a JSON-serializable dict with meaningful keys
5. Do NOT import ToolSpec / ArgSpec
6. For optional libs use: try: import X; except ImportError: return {"error": "X not installed"}
7. Keep code concise but complete — it must actually run
"""

_CUSTOM_TOOLS_DIR = APP_ROOT / "services" / "custom_tools"


class ToolDesignRequest(BaseModel):
    intent: str                          # natural language description
    extra_context: str = ""             # optional extra context
    model_override: Optional[str] = None # force a specific node role


class ToolInstallRequest(BaseModel):
    name: str
    description: str
    category: str = "misc"
    needs_visual: bool = False
    args: List[dict] = []
    python_code: str
    explanation: str = ""


@app.post("/api/agent/tool/design")
async def design_agent_tool(req: ToolDesignRequest):
    """Call LLM to draft a new tool spec + Python implementation."""
    from services.computer_tools import TOOL_REGISTRY

    existing = ", ".join(list(TOOL_REGISTRY.keys())[:20]) + "…"
    user_msg = (
        f"Intent: {req.intent}\n\n"
        f"Already-registered tools (don't duplicate): {existing}\n"
        + (f"\nExtra context: {req.extra_context}" if req.extra_context else "")
    )

    role = req.model_override or "dispatcher"
    try:
        raw = await console.call_node(
            role=role,
            user_input=user_msg,
            protocol_text=_TOOL_DESIGNER_PROMPT,
            extra_context="",
        )
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    # Extract JSON from response (strip markdown fences if any)
    import re as _re
    json_str = raw.strip()
    fence = _re.search(r"```(?:json)?\s*([\s\S]+?)```", json_str)
    if fence:
        json_str = fence.group(1).strip()
    # Fallback: find first { … }
    if not json_str.startswith("{"):
        m = _re.search(r"\{[\s\S]*\}", json_str)
        if m:
            json_str = m.group(0)

    try:
        parsed = json.loads(json_str)
    except Exception:
        raise HTTPException(500, f"LLM returned non-JSON: {raw[:400]}")

    # Validate required fields
    for field_name in ("name", "description", "python_code"):
        if field_name not in parsed:
            raise HTTPException(500, f"LLM response missing field '{field_name}'")

    # Syntax-check generated code
    import ast as _ast
    try:
        _ast.parse(parsed["python_code"])
    except SyntaxError as e:
        parsed["syntax_warning"] = f"Syntax error in generated code: {e}"

    return {"ok": True, "draft": parsed}


@app.post("/api/agent/tool/install")
async def install_agent_tool(req: ToolInstallRequest):
    """Validate, write tool file, and hot-reload the custom tools registry."""
    import ast as _ast

    # Validate name
    if not req.name.replace("_", "").isalnum() or not req.name[0].isalpha():
        raise HTTPException(400, "Tool name must be snake_case.")

    # Syntax check
    try:
        _ast.parse(req.python_code)
    except SyntaxError as e:
        raise HTTPException(400, f"Syntax error in python_code: {e}")

    # Must define execute()
    tree = _ast.parse(req.python_code)
    fn_names = [n.name for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef)]
    if "execute" not in fn_names:
        raise HTTPException(400, "python_code must define a function named 'execute'.")

    # Build tool module source
    args_repr = json.dumps(req.args, ensure_ascii=False, indent=4)
    _parts = [
        '"""\nURUK auto-generated tool: ' + req.name + "\n",
        "Designed by AI Tool Designer (v8.45)\n",
        "Description: " + req.description + "\n",
        '"""\n',
        "from services.computer_tools import ToolSpec, ArgSpec\n\n",
        "SPEC = ToolSpec(\n",
        "    name=" + repr(req.name) + ",\n",
        "    description=" + repr(req.description) + ",\n",
        "    args=[\n",
        "        ArgSpec(**a) for a in " + args_repr + "\n",
        "    ],\n",
        "    needs_visual=" + repr(req.needs_visual) + ",\n",
        "    category=" + repr(req.category) + ",\n",
        ")\n\n",
        req.python_code, "\n",
    ]
    module_src = "".join(_parts)

    # Write file
    _CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    init_path = _CUSTOM_TOOLS_DIR / "__init__.py"
    if not init_path.exists():
        init_path.write_text("# URUK custom tools\n", encoding="utf-8")

    tool_path = _CUSTOM_TOOLS_DIR / f"{req.name}.py"
    tool_path.write_text(module_src, encoding="utf-8")

    # Hot-reload
    from services.computer_tools import _load_custom_tools
    loaded = _load_custom_tools()

    return {
        "ok": True,
        "name": req.name,
        "file": str(tool_path.relative_to(APP_ROOT)),
        "reloaded_tools": loaded,
    }


@app.post("/api/agent/tool/reload")
async def reload_agent_tools():
    """Rescan services/custom_tools/ and hot-reload all custom tools."""
    from services.computer_tools import _load_custom_tools
    loaded = _load_custom_tools()
    tools = _get_merged_tools()
    return {"ok": True, "reloaded": loaded, "total_tools": len(tools)}


# ─────────────────────────────────────────────────────────────────
# Direct tool execution — single tool by name + args
# POST /api/agent/execute → run one tool synchronously
# ─────────────────────────────────────────────────────────────────

class ToolExecuteRequest(BaseModel):
    name: str
    args: Dict[str, Any] = {}


@app.post("/api/agent/execute")
async def execute_agent_tool_direct(req: ToolExecuteRequest):
    """Execute a single agent tool by name with given args."""
    import asyncio
    from services.computer_tools import execute_tool
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, execute_tool, req.name, req.args)
    return {
        "ok": result.ok,
        "tool": result.tool,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }


# ─────────────────────────────────────────────────────────────────
# SELF-UPGRADE API
# POST /api/upgrade/audit   → 掃描系統+對話，識別缺陷，生成升級建議
# POST /api/upgrade/learn   → 上網學習最新功能，生成升級建議
# ─────────────────────────────────────────────────────────────────

class UpgradeRequest(BaseModel):
    relay_target: str = "claude"   # "claude" / "codex" / "cowork" / "claude_code" / "chatgpt" / "local"
    max_sessions: int = 10          # audit: 最多分析多少個 session
    search_queries: List[str] = []  # learn: 額外搜索詞（留空用默認）
    auto_install: bool = False       # True = Claude 回覆後自動解析並安裝（實驗性）


class UpgradeLoopRequest(BaseModel):
    relay_target: str = "codex"
    max_sessions: int = 10
    search_queries: List[str] = []
    modes: List[str] = ["audit", "learn"]
    interval_seconds: float = 30.0


class UpgradeReportRequest(BaseModel):
    plan_limit: int = 8
    log_limit: int = 12
    run_gates: bool = True
    run_prompt_regression: bool = True
    write: bool = True


class StabilityCheckRequest(BaseModel):
    require_api: bool = True
    skip_pytest: bool = True
    write: bool = True


class PromptRegressionRequest(BaseModel):
    run_benchmark: bool = True
    run_quick_eval: bool = True
    compare_latest_episode: bool = True
    strict_episode: bool = False
    update_baseline: bool = False
    label: str = "ui"
    write: bool = True


_UPGRADE_LOOP_TASK: Optional[asyncio.Task] = None
_UPGRADE_LOOP_LOCK = asyncio.Lock()
_UPGRADE_LOOP_STATE: Dict = {
    "running": False,
    "pause_requested": False,
    "status": "idle",       # idle / running / health_check / sleeping / pause_requested / paused / error / health_failed
    "current_mode": None,
    "iteration": 0,
    "started_at": None,
    "updated_at": None,
    "last_plan_id": None,
    "last_status": None,
    "last_summary": "",
    "last_health": None,
    "last_error": "",
    "history": [],
}


def _upgrade_loop_public_state() -> Dict:
    state = dict(_UPGRADE_LOOP_STATE)
    state["history"] = list(_UPGRADE_LOOP_STATE.get("history", []))[-12:]
    return state


def _runtime_code_stamp() -> Dict:
    tracked = [
        APP_ROOT / "app.py",
        APP_ROOT / "upgrade_engine.py",
        APP_ROOT / "services" / "app_controller.py",
        APP_ROOT / "services" / "relay_protocol.py",
        APP_ROOT / "services" / "computer_tools.py",
        STATIC_DIR / "index.html",
        STATIC_DIR / "app.js",
        STATIC_DIR / "style_v2.css",
    ]
    files = []
    latest = 0.0
    for path in tracked:
        try:
            stat = path.stat()
        except OSError:
            continue
        latest = max(latest, stat.st_mtime)
        files.append({
            "path": str(path),
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "size": stat.st_size,
        })
    return {
        "latest_mtime": datetime.fromtimestamp(latest).isoformat() if latest else "",
        "tracked_files": files,
    }


async def _set_upgrade_loop_state(**updates) -> None:
    async with _UPGRADE_LOOP_LOCK:
        _UPGRADE_LOOP_STATE.update(updates)
        _UPGRADE_LOOP_STATE["updated_at"] = datetime.now().isoformat()


def _record_upgrade_loop_history(entry: Dict) -> None:
    hist = _UPGRADE_LOOP_STATE.setdefault("history", [])
    hist.append(entry | {"timestamp": datetime.now().isoformat()})
    del hist[:-20]


def _is_relay_limit_error(message: str) -> bool:
    text = (message or "").lower()
    return any(
        marker in text
        for marker in (
            "session limit",
            "rate limit",
            "quota",
            "resource_exhausted",
            "too many requests",
            "resets ",
        )
    )


def _upgrade_relay_failure_summary(target: str, error: str) -> str:
    if _is_relay_limit_error(error):
        return (
            f"{target} 已達到當前使用限額，今次升級未執行。"
            "可喺自我升級面板改選 Codex 或其他 relay 再試。"
        )
    return f"{target} relay 失敗：{error}"


def _check_upgrade_loop_iteration(mode: str, result: Dict) -> Dict:
    """Deterministic final gate before a loop iteration is allowed to complete."""
    issues = []
    warnings = []
    plan_id = ""
    plan_status = ""

    if not isinstance(result, dict):
        return {
            "ok": False,
            "mode": mode,
            "checked_at": datetime.now().isoformat(),
            "issues": ["upgrade endpoint returned a non-dict result"],
            "warnings": [],
        }

    plan_id = str(result.get("plan_id") or "")
    result_status = str(result.get("status") or "")
    installed = list(result.get("installed") or [])

    if not plan_id:
        issues.append("missing plan_id")
    if result_status in {"failed", "error"}:
        # "failed" is treated as a soft warning when it's purely a validation
        # conflict (all proposed tools already installed) — no issue.
        # Only escalate to a hard issue for genuine relay/LLM errors.
        _relay_err = str(result.get("relay_error") or "")
        if _relay_err and result_status in {"failed", "error"}:
            issues.append(f"relay error: {_relay_err[:120]}")
        elif result_status == "error":
            issues.append(f"endpoint returned status={result_status}")
        # plan.status=failed due to validation conflicts → handled below
    elif result_status == "review_required":
        issues.append("endpoint requires human review before continuing")
    elif result_status == "rolled_back":
        issues.append("endpoint rolled back installed tools")
    elif result_status and result_status != "done":
        warnings.append(f"endpoint returned non-final status={result_status}")

    if plan_id:
        try:
            from upgrade_engine import UpgradePlan
            plan = UpgradePlan.load(plan_id)
            plan_status = str(plan.status or "")
            installed = list(plan.installed_tools or installed)

            if plan_status in {"failed", "error"}:
                issues.append(f"plan status={plan_status}")
            elif plan_status == "review_required":
                issues.append("plan requires human review before continuing")
            elif plan_status == "rolled_back":
                issues.append("plan rolled back installed tools")
            elif plan_status and plan_status != "done":
                warnings.append(f"plan status={plan_status}")

            failed_steps = [s.action for s in plan.steps if s.status == "failed"]
            if failed_steps:
                issues.append("failed steps: " + ", ".join(failed_steps))

            blocked_events = [
                e for e in (plan.executor_events or [])
                if e.get("outcome") in {"blocked", "denied"}
                or (e.get("decision") or {}).get("requires_human") is True
            ]
            if blocked_events:
                issues.append(f"executor blocked/denied {len(blocked_events)} step(s)")

            validate_step = plan.get_step("validate_code")
            validate_output = validate_step.output if validate_step else {}
            if plan.tool_specs and validate_output:
                passed = int(validate_output.get("passed") or 0)
                if passed <= 0:
                    issues.append("no tool spec passed validation")

            smoke_step = plan.get_step("smoke_test")
            smoke_output = smoke_step.output if smoke_step else {}
            if installed:
                if not smoke_output:
                    warnings.append("installed tools have no smoke test output")
                else:
                    smoke_failed = list(smoke_output.get("failed") or [])
                    smoke_passed = list(smoke_output.get("passed") or [])
                    if smoke_failed and len(smoke_failed) >= len(installed):
                        issues.append("all installed tools failed smoke test")
                    elif smoke_failed:
                        warnings.append("some installed tools failed smoke test: " + ", ".join(smoke_failed))
                    if not smoke_passed and not smoke_failed:
                        warnings.append("smoke test returned no pass/fail details")

                eval_step = plan.get_step("post_install_eval")
                eval_output = eval_step.output if eval_step else {}
                benchmark = eval_output.get("benchmark") if isinstance(eval_output, dict) else {}
                if benchmark and benchmark.get("passed") is False:
                    failed_cases = benchmark.get("failed_cases") or []
                    issues.append("coordinate benchmark failed: " + ", ".join(map(str, failed_cases)))
                if isinstance(eval_output, dict) and eval_output.get("regressed"):
                    issues.append(f"post-install regression: {eval_output.get('reason') or 'unknown'}")

            log_step = plan.get_step("write_log")
            if installed and (not log_step or log_step.status != "done"):
                warnings.append("installed tools were not written to upgrade log")

            if plan_status == "done" and not installed:
                warnings.append("plan completed without installing tools")
        except Exception as e:
            issues.append(f"cannot load/check plan {plan_id}: {type(e).__name__}: {e}")

    return {
        "ok": not issues,
        "mode": mode,
        "plan_id": plan_id,
        "result_status": result_status,
        "plan_status": plan_status,
        "installed": installed,
        "issues": issues,
        "warnings": warnings,
        "checked_at": datetime.now().isoformat(),
    }


def _build_audit_prompt(max_sessions: int = 10) -> str:
    """掃描系統現有工具 + 最近對話，生成審計報告 prompt。"""
    from services.computer_tools import TOOL_REGISTRY
    import json as _json
    from upgrade_engine import step_scan_sessions

    tool_names = list(TOOL_REGISTRY.keys())

    # 讀最近 N 個 harness episode（machine-readable replay package）
    session_snippets = []
    session_scan = step_scan_sessions(max_sessions)
    for item in session_scan.get("snippets", [])[:max_sessions]:
        err = "; ".join(item.get("error_reasons") or [])
        session_snippets.append(
            "EPISODE: {episode}\nMODE: {mode}\nINPUT: {input}\n"
            "KNOWLEDGE_CLEAN: {knowledge_clean}\nTRACE_COUNT: {trace_count}\n"
            "DENSITY: {density}\nVERDICT: {verdict}\nERROR: {error}".format(
                episode=item.get("episode_id") or item.get("source_file") or "",
                mode=item.get("mode") or "",
                input=str(item.get("input") or "")[:240],
                knowledge_clean=item.get("knowledge_clean"),
                trace_count=item.get("knowledge_trace_count", 0),
                density=item.get("density") or "",
                verdict=item.get("council_verdict") or "",
                error=err[:220],
            )
        )

    # 讀升級日誌
    upgrade_log = []
    log_path = DATA_DIR / "upgrade_log.jsonl"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").strip().splitlines()[-10:]:
            try:
                upgrade_log.append(_json.loads(line).get("tool_name", ""))
            except Exception:
                pass

    sessions_text = "\n---\n".join(session_snippets) if session_snippets else "（無近期對話記錄）"
    upgrade_text  = ", ".join(upgrade_log) if upgrade_log else "（無）"

    return f"""[UPGRADE_AUDIT]
請啟動 uruk-audit skill，分析以下 URUK Trinity Console 系統狀態，
識別缺陷同不足，然後提出最多 3 個具體嘅新工具建議。

=== 現有工具列表（{len(tool_names)} 個）===
{", ".join(tool_names)}

=== 已安裝嘅自定義工具 ===
{upgrade_text}

=== 最近 {len(session_snippets)} 個 harness episode 摘要（source={session_scan.get("source", "")}）===
{sessions_text}

=== 你嘅任務 ===
1. 識別工具集嘅缺口（用戶嘗試做但失敗嘅操作、常見錯誤模式）
2. 識別可靠性問題（哪類工具容易失敗）
3. 主動讀取 C:\\uruk-trinity-console\\services\\computer_tools.py 驗證工具清單
4. 提出最多 3 個新工具建議，每個用以下格式：

[UPGRADE_REQUEST]
需求：<功能描述>
原因：<點解需要，解決咩問題>
類別：<misc|file|screen|mouse|keyboard|nav|state|clipboard|wait>

只輸出建議，唔需要其他解釋。"""


def _build_learn_prompt(extra_queries: List[str] = []) -> str:
    """搜索最新 AI agent 工具功能，生成學習升級 prompt。"""
    from services.computer_tools import TOOL_REGISTRY
    tool_names = list(TOOL_REGISTRY.keys())

    queries = [
        "Windows desktop automation Python tools 2025 2026",
        "AI agent computer use new capabilities pyautogui alternative",
        "Python GUI automation accessibility API best practices",
    ] + extra_queries

    return f"""[UPGRADE_LEARN]
請啟動 uruk-learn skill，上網學習最新技術，然後為 URUK Trinity Console 提出升級建議。

請搜索以下關鍵詞：
{chr(10).join(f'   - {q}' for q in queries)}

URUK 現有工具（{len(tool_names)} 個，唔要重複）：
{", ".join(tool_names)}

識別 URUK 缺少但有用嘅功能，提出最多 3 個建議，每個用以下格式：
[UPGRADE_REQUEST]
需求：<功能描述（基於搜索結果）>
原因：<呢個功能點樣令 URUK 更強>
類別：<類別>
參考：<搜索到嘅相關技術/庫名稱>

只輸出建議，唔需要其他解釋。"""


@app.post("/api/upgrade/audit")
async def upgrade_audit(req: UpgradeRequest):
    """
    URUK 自動掃描系統（Steps 1-4），生成計劃書，
    然後發送 Step 5 設計任務到 Claude relay。
    Claude 只需填工具代碼，其餘由 URUK 自動完成。
    """
    from upgrade_engine import build_plan
    from services.app_controller import send_and_receive as _ac_sr, list_apps as _ac_list

    target = "claude" if req.relay_target == "cowork" else req.relay_target

    # URUK 執行 system steps，生成計劃書
    plan = build_plan(mode="audit", relay_target=target, max_sessions=req.max_sessions)
    claude_prompt = plan.get_step("design_tools").input

    if target == "local":
        try:
            raw = await console.call_node(
                role="dispatcher",
                user_input=claude_prompt,
                protocol_text="你係 URUK 工具設計師。根據指定格式輸出工具 spec，唔需要解釋。",
                extra_context="",
            )
            # 自動執行安裝
            from upgrade_engine import execute_plan_after_claude
            plan = await execute_plan_after_claude(plan.plan_id, raw)
            return {"ok": True, "plan_id": plan.plan_id, "status": plan.status,
                    "summary": plan.summary, "installed": plan.installed_tools,
                    "review_count": len(getattr(plan, "review_tool_specs", []))}
        except Exception as e:
            raise HTTPException(500, f"Local LLM failed: {e}")

    apps = _ac_list()
    app_meta = next((a for a in apps if a["key"] == target), None)
    if not app_meta:
        raise HTTPException(400, f"Unknown relay target: {target}")
    if not app_meta.get("running"):
        raise HTTPException(400, f"{app_meta.get('display', target)} 未運行")

    relay_timeout = 90.0 if target == "claude_code" else 300.0 if target == "codex" else 180.0 if target == "chatgpt" else 120.0
    result = await _ac_sr(target, claude_prompt, timeout=relay_timeout, relay_mode="upgrade", new_conversation=True)
    fallback_target = ""
    if not result["ok"] and target == "chatgpt":
        primary_error = str(result.get("error") or "unknown error")
        fallback = await _ac_sr("codex", claude_prompt, timeout=300.0, relay_mode="upgrade", new_conversation=True)
        if fallback.get("ok"):
            result = fallback
            fallback_target = "codex"
            plan.summary += " ChatGPT Desktop relay unavailable; fell back to Codex."
        else:
            result["error"] = primary_error + "; codex fallback failed: " + str(fallback.get("error") or "unknown error")
    if not result["ok"]:
        relay_error = str(result.get("error") or "unknown error")
        plan.status = "failed"
        plan.summary += " " + _upgrade_relay_failure_summary(target, relay_error)
        plan.save()
        return {
            "ok": True,
            "plan_id": plan.plan_id,
            "status": plan.status,
            "summary": plan.summary,
            "installed": plan.installed_tools,
            "review_count": len(getattr(plan, "review_tool_specs", [])),
            "gap_count": len(plan.gaps),
            "relay_error": relay_error,
            "fallback_target": fallback_target or ("codex" if target == "claude_code" and _is_relay_limit_error(relay_error) else ""),
        }

    # Claude 回覆後，URUK 自動執行 Steps 6-10
    from upgrade_engine import execute_plan_after_claude
    plan = await execute_plan_after_claude(plan.plan_id, result.get("response", ""))
    if fallback_target:
        plan.summary += f" Relay fallback used: {fallback_target}."
        plan.save()

    return {
        "ok": True,
        "plan_id": plan.plan_id,
        "status": plan.status,
        "summary": plan.summary,
        "installed": plan.installed_tools,
        "review_count": len(getattr(plan, "review_tool_specs", [])),
        "gap_count": len(plan.gaps),
        "fallback_target": fallback_target,
    }


@app.post("/api/upgrade/learn")
async def upgrade_learn(req: UpgradeRequest):
    """
    上網學習升級：URUK 生成計劃書 + 搜索詞，
    發送到 Claude relay（Claude 需搜索後設計工具），
    URUK 收到回覆後自動安裝。
    """
    from upgrade_engine import build_plan, execute_plan_after_claude
    from services.app_controller import send_and_receive as _ac_sr, list_apps as _ac_list
    from services.relay_protocol import upgrade_output_contract as _upgrade_output_contract

    target = "claude" if req.relay_target == "cowork" else req.relay_target

    # 用 learn 模式建立計劃書（掃描現有工具）
    plan = build_plan(mode="learn", relay_target=target, max_sessions=5)

    # 覆蓋 claude step input 為 learn 版本 prompt（附加搜索詞）
    learn_prompt = _build_learn_prompt(req.search_queries)
    # 把計劃書 ID 注入，讓 Claude 回覆用正確格式
    learn_prompt = learn_prompt.replace(
        "[UPGRADE_LEARN]",
        f"[UPGRADE_LEARN]\n計劃書 ID：{plan.plan_id}\n請用 [TOOL_SPEC:{plan.plan_id}] 格式輸出建議"
    )
    learn_prompt += "\n\n" + _upgrade_output_contract(plan.plan_id, 3)
    plan.get_step("design_tools").input = learn_prompt
    plan.save()

    if target == "local":
        try:
            raw = await console.call_node(
                role="dispatcher",
                user_input=learn_prompt,
                protocol_text="你係 URUK 工具設計師。根據指定格式輸出工具 spec。",
                extra_context="",
            )
            plan = await execute_plan_after_claude(plan.plan_id, raw)
            return {"ok": True, "plan_id": plan.plan_id, "status": plan.status,
                    "summary": plan.summary, "installed": plan.installed_tools,
                    "review_count": len(getattr(plan, "review_tool_specs", []))}
        except Exception as e:
            raise HTTPException(500, f"Local LLM failed: {e}")

    apps = _ac_list()
    app_meta = next((a for a in apps if a["key"] == target), None)
    if not app_meta:
        raise HTTPException(400, f"Unknown relay target: {target}")
    if not app_meta.get("running"):
        raise HTTPException(400, f"{app_meta.get('display', target)} 未運行")

    relay_timeout = 90.0 if target == "claude_code" else 300.0 if target == "codex" else 180.0 if target == "chatgpt" else 120.0
    result = await _ac_sr(target, learn_prompt, timeout=relay_timeout, relay_mode="upgrade", new_conversation=True)
    fallback_target = ""
    if not result["ok"] and target == "chatgpt":
        primary_error = str(result.get("error") or "unknown error")
        fallback = await _ac_sr("codex", learn_prompt, timeout=300.0, relay_mode="upgrade", new_conversation=True)
        if fallback.get("ok"):
            result = fallback
            fallback_target = "codex"
            plan.summary += " ChatGPT Desktop relay unavailable; fell back to Codex."
        else:
            result["error"] = primary_error + "; codex fallback failed: " + str(fallback.get("error") or "unknown error")
    if not result["ok"]:
        relay_error = str(result.get("error") or "unknown error")
        plan.status = "failed"
        plan.summary += " " + _upgrade_relay_failure_summary(target, relay_error)
        plan.save()
        return {
            "ok": True,
            "plan_id": plan.plan_id,
            "status": plan.status,
            "summary": plan.summary,
            "installed": plan.installed_tools,
            "review_count": len(getattr(plan, "review_tool_specs", [])),
            "relay_error": relay_error,
            "fallback_target": fallback_target or ("codex" if target == "claude_code" and _is_relay_limit_error(relay_error) else ""),
        }

    plan = await execute_plan_after_claude(plan.plan_id, result.get("response", ""))
    if fallback_target:
        plan.summary += f" Relay fallback used: {fallback_target}."
        plan.save()
    return {
        "ok": True,
        "plan_id": plan.plan_id,
        "status": plan.status,
        "summary": plan.summary,
        "installed": plan.installed_tools,
        "review_count": len(getattr(plan, "review_tool_specs", [])),
        "fallback_target": fallback_target,
    }


async def _upgrade_loop_worker(req: UpgradeLoopRequest) -> None:
    modes = [m for m in (req.modes or ["audit", "learn"]) if m in ("audit", "learn")]
    if not modes:
        modes = ["audit", "learn"]
    interval = max(3.0, min(float(req.interval_seconds or 30.0), 3600.0))

    await _set_upgrade_loop_state(
        running=True,
        pause_requested=False,
        status="running",
        current_mode=None,
        iteration=0,
        started_at=datetime.now().isoformat(),
        last_error="",
    )

    iteration = 0
    try:
        while True:
            if _UPGRADE_LOOP_STATE.get("pause_requested"):
                await _set_upgrade_loop_state(
                    running=False,
                    status="paused",
                    current_mode=None,
                    pause_requested=False,
                )
                return

            mode = modes[iteration % len(modes)]
            await _set_upgrade_loop_state(
                status="running",
                current_mode=mode,
                iteration=iteration + 1,
                last_error="",
            )

            loop_req = UpgradeRequest(
                relay_target=req.relay_target,
                max_sessions=req.max_sessions,
                search_queries=req.search_queries,
                auto_install=True,
            )

            try:
                result = (
                    await upgrade_audit(loop_req)
                    if mode == "audit"
                    else await upgrade_learn(loop_req)
                )
                await _set_upgrade_loop_state(status="health_check")
                health = _check_upgrade_loop_iteration(mode, result)
                _record_upgrade_loop_history({
                    "mode": mode,
                    "ok": health["ok"],
                    "plan_id": result.get("plan_id"),
                    "status": result.get("status"),
                    "summary": result.get("summary", ""),
                    "installed": result.get("installed", []),
                    "health": health,
                })
                await _set_upgrade_loop_state(
                    last_plan_id=result.get("plan_id"),
                    last_status=result.get("status"),
                    last_summary=result.get("summary", ""),
                    last_health=health,
                )
                if not health["ok"]:
                    await _set_upgrade_loop_state(
                        running=False,
                        status="health_failed",
                        current_mode=None,
                        last_error="；".join(health.get("issues") or ["upgrade health check failed"]),
                    )
                    return
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                _record_upgrade_loop_history({"mode": mode, "ok": False, "error": err})
                await _set_upgrade_loop_state(status="error", last_error=err)

            iteration += 1
            if _UPGRADE_LOOP_STATE.get("pause_requested"):
                await _set_upgrade_loop_state(
                    running=False,
                    status="paused",
                    current_mode=None,
                    pause_requested=False,
                )
                return

            await _set_upgrade_loop_state(status="sleeping", current_mode=None)
            slept = 0.0
            while slept < interval:
                if _UPGRADE_LOOP_STATE.get("pause_requested"):
                    await _set_upgrade_loop_state(
                        running=False,
                        status="paused",
                        current_mode=None,
                        pause_requested=False,
                    )
                    return
                step = min(1.0, interval - slept)
                await asyncio.sleep(step)
                slept += step
    except Exception as e:
        await _set_upgrade_loop_state(
            running=False,
            status="error",
            current_mode=None,
            last_error=f"{type(e).__name__}: {e}",
        )


@app.post("/api/upgrade/loop/start")
async def start_upgrade_loop(req: UpgradeLoopRequest):
    """Start continuous self-upgrade until graceful pause is requested."""
    global _UPGRADE_LOOP_TASK
    if _UPGRADE_LOOP_TASK and not _UPGRADE_LOOP_TASK.done():
        return {"ok": True, "already_running": True, "state": _upgrade_loop_public_state()}

    async with _UPGRADE_LOOP_LOCK:
        _UPGRADE_LOOP_STATE.update({
            "running": True,
            "pause_requested": False,
            "status": "starting",
            "current_mode": None,
            "iteration": 0,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "last_error": "",
            "last_health": None,
            "history": [],
        })
    _UPGRADE_LOOP_TASK = asyncio.create_task(_upgrade_loop_worker(req))
    return {"ok": True, "started": True, "state": _upgrade_loop_public_state()}


@app.post("/api/upgrade/loop/pause")
async def pause_upgrade_loop():
    """
    Request graceful pause. Current audit/learn/install work is allowed to finish;
    the loop stops before the next iteration.
    """
    if not (_UPGRADE_LOOP_TASK and not _UPGRADE_LOOP_TASK.done()):
        await _set_upgrade_loop_state(
            running=False,
            pause_requested=False,
            status="paused",
            current_mode=None,
        )
        return {"ok": True, "state": _upgrade_loop_public_state()}
    await _set_upgrade_loop_state(pause_requested=True, status="pause_requested")
    return {
        "ok": True,
        "message": "Pause requested. Current upgrade iteration will finish before stopping.",
        "state": _upgrade_loop_public_state(),
    }


@app.get("/api/upgrade/loop/status")
async def upgrade_loop_status():
    if _UPGRADE_LOOP_TASK and _UPGRADE_LOOP_TASK.done() and _UPGRADE_LOOP_STATE.get("running"):
        await _set_upgrade_loop_state(running=False, status="idle", current_mode=None)
    return {"ok": True, "state": _upgrade_loop_public_state()}


@app.get("/api/upgrade/plans")
async def list_upgrade_plans():
    """返回最近嘅升級計劃書列表。"""
    from upgrade_engine import list_plans
    return {"plans": list_plans(20)}


@app.get("/api/upgrade/plan/{plan_id}")
async def get_upgrade_plan(plan_id: str):
    """返回指定計劃書嘅完整內容。"""
    from upgrade_engine import UpgradePlan
    try:
        plan = UpgradePlan.load(plan_id)
        return plan.to_dict()
    except FileNotFoundError:
        raise HTTPException(404, f"Plan {plan_id} not found")


@app.get("/api/upgrade/plan/{plan_id}/snapshot-diff")
async def get_upgrade_plan_snapshot_diff(plan_id: str):
    """Diff current runtime files against a plan's pre-install snapshot."""
    from upgrade_engine import UpgradePlan
    from services.upgrade_snapshot import diff_upgrade_snapshot, load_upgrade_snapshot

    try:
        plan = UpgradePlan.load(plan_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Plan {plan_id} not found")

    snapshot_ref = ((plan.snapshots or {}).get("pre_install") or {})
    snapshot_path = snapshot_ref.get("path")
    if not snapshot_path:
        return {
            "ok": True,
            "plan_id": plan_id,
            "has_snapshot": False,
            "snapshot": snapshot_ref,
            "diff": None,
        }

    try:
        snapshot = await asyncio.to_thread(load_upgrade_snapshot, snapshot_path)
        snapshot.setdefault("path", snapshot_path)
        diff = await asyncio.to_thread(diff_upgrade_snapshot, snapshot)
    except FileNotFoundError:
        raise HTTPException(404, f"Snapshot manifest not found: {snapshot_path}")
    except Exception as e:
        raise HTTPException(500, f"Cannot diff snapshot: {type(e).__name__}: {e}")

    return {
        "ok": True,
        "plan_id": plan_id,
        "has_snapshot": True,
        "snapshot": snapshot_ref,
        "diff": diff,
    }


@app.post("/api/upgrade/plan/{plan_id}/apply")
async def apply_claude_response(plan_id: str, body: dict):
    """
    手動觸發：把 Claude 嘅回覆套用到計劃書並執行安裝。
    用於 Claude relay 冇自動返回嘅情況。
    """
    from upgrade_engine import execute_plan_after_claude
    claude_response = body.get("response", "")
    if not claude_response:
        raise HTTPException(400, "Missing 'response' field")
    plan = await execute_plan_after_claude(plan_id, claude_response)
    return {"ok": True, "plan_id": plan_id, "status": plan.status,
            "summary": plan.summary, "installed": plan.installed_tools,
            "review_count": len(getattr(plan, "review_tool_specs", []))}


@app.get("/api/upgrade/log")
async def get_upgrade_log():
    """返回升級日誌。"""
    log_path = DATA_DIR / "upgrade_log.jsonl"
    entries = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").strip().splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return {"entries": list(reversed(entries)), "count": len(entries)}


@app.get("/api/upgrade/gates")
async def upgrade_gate_preflight():
    """Read-only preflight for self-upgrade post-install gates."""
    from upgrade_engine import run_upgrade_gate_preflight

    return run_upgrade_gate_preflight()


def _stability_report_path() -> Path:
    return DATA_DIR / "reports" / "system_stability_last.json"


def _prompt_regression_report_path() -> Path:
    return DATA_DIR / "reports" / "prompt_regression_last.json"


@app.get("/api/upgrade/stability/latest")
async def latest_upgrade_stability():
    """Return the last persisted one-command stability report, if present."""
    path = _stability_report_path()
    if not path.exists():
        return {"ok": True, "report": None, "path": str(path)}
    try:
        return {"ok": True, "report": json.loads(path.read_text(encoding="utf-8")), "path": str(path)}
    except Exception as e:
        raise HTTPException(500, f"Cannot read stability report: {type(e).__name__}: {e}")


@app.post("/api/upgrade/stability")
async def run_upgrade_stability(req: StabilityCheckRequest, request: Request):
    """Run the deterministic stability harness from the self-upgrade UI/API."""
    from tools.system_stability_check import run_stability_checks

    api_url = str(request.base_url).rstrip("/")
    report = await asyncio.to_thread(
        run_stability_checks,
        api_url=api_url,
        require_api=bool(req.require_api),
        skip_pytest=bool(req.skip_pytest),
    )
    report["api_url"] = api_url
    if req.write:
        path = _stability_report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["written_path"] = str(path)
    return report


@app.get("/api/upgrade/prompt-regression/latest")
async def latest_prompt_regression():
    """Return the last persisted prompt regression report, if present."""
    path = _prompt_regression_report_path()
    if not path.exists():
        return {"ok": True, "report": None, "path": str(path)}
    try:
        return {"ok": True, "report": json.loads(path.read_text(encoding="utf-8")), "path": str(path)}
    except Exception as e:
        raise HTTPException(500, f"Cannot read prompt regression report: {type(e).__name__}: {e}")


@app.post("/api/upgrade/prompt-regression")
async def run_prompt_regression(req: PromptRegressionRequest):
    """Run prompt/protocol fingerprint regression checks from UI/API."""
    from services.prompt_regression import DEFAULT_BASELINE_PATH, run_prompt_regression_check

    report = await asyncio.to_thread(
        run_prompt_regression_check,
        root=APP_ROOT,
        baseline_path=DEFAULT_BASELINE_PATH,
        update_baseline=bool(req.update_baseline),
        run_benchmark=bool(req.run_benchmark),
        run_quick_eval=bool(req.run_quick_eval),
        compare_latest_episode=bool(req.compare_latest_episode),
        strict_episode=bool(req.strict_episode),
        label=str(req.label or "ui"),
    )
    if req.write:
        path = _prompt_regression_report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["written_path"] = str(path)
    return report


@app.post("/api/upgrade/report")
async def generate_upgrade_report(req: UpgradeReportRequest):
    """Generate a JSON + Markdown self-upgrade report artifact."""
    from services.upgrade_report import generate_self_upgrade_report

    return generate_self_upgrade_report(
        root=APP_ROOT,
        plan_limit=max(1, min(int(req.plan_limit or 8), 50)),
        log_limit=max(0, min(int(req.log_limit or 12), 100)),
        run_gates=bool(req.run_gates),
        run_prompt_regression=bool(req.run_prompt_regression),
        write=bool(req.write),
    )


@app.get("/api/upgrade/reports")
async def list_upgrade_reports():
    """List generated self-upgrade report artifacts."""
    from services.upgrade_report import list_reports

    return {"reports": list_reports(root=APP_ROOT, limit=20)}


@app.get("/api/upgrade/report/{report_id}")
async def get_upgrade_report(report_id: str):
    """Return one generated self-upgrade report."""
    from services.upgrade_report import load_report

    report = load_report(report_id, root=APP_ROOT)
    if not report:
        raise HTTPException(404, f"Report {report_id} not found")
    return report


class VesselLocationRequest(BaseModel):
    lat: float
    lon: float
    label: str = ""
    source: str = "manual"
    confidence: float = 1.0
    note: str = ""


class VesselNoteRequest(BaseModel):
    title: str = ""
    body: str = ""
    kind: str = "system_note"
    source: str = "manual"


class VesselCalendarEventRequest(BaseModel):
    title: str
    start: str
    end: str = ""
    location: str = ""
    description: str = ""
    source: str = "manual"


class WorldSimRequest(BaseModel):
    input_text: str = ""
    horizon: str = "short"


class WorldForecastNewsSource(BaseModel):
    url: str = ""
    title: str = ""
    text: str = ""
    content: str = ""
    snippet: str = ""
    published_at: str = ""
    date: str = ""
    source: str = ""
    location: str = ""
    place: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    fetched_at: str = ""


class WorldForecastRequest(BaseModel):
    input_text: str = ""
    horizon: str = "medium"
    news_sources: List[WorldForecastNewsSource] = Field(default_factory=list)


class WorldGeoTimelineRequest(WorldForecastRequest):
    auto_news: bool = False
    max_news: int = Field(default=6, ge=3, le=12)
    persist_revision: bool = True


@app.get("/api/vessel/profile")
async def vessel_profile(refresh: bool = False):
    """Return the current VesselProfile and hardware-derived tool gaps."""
    from services.computer_tools import TOOL_REGISTRY

    payload = vessel_api_payload(refresh=refresh, tool_names=TOOL_REGISTRY.keys())
    return {"ok": True, **payload}


@app.get("/api/vessel/state")
async def vessel_state():
    """Return persisted vessel location, notes, calendar, and profile summary."""
    from services.computer_tools import TOOL_REGISTRY
    from services.vessel_state import load_state

    payload = vessel_api_payload(refresh=False, tool_names=TOOL_REGISTRY.keys())
    return {
        "ok": True,
        "state": load_state(DATA_DIR),
        "profile": payload.get("summary") or {},
        "hardware_gaps": payload.get("hardware_gaps") or [],
    }


@app.post("/api/vessel/location")
async def update_vessel_location(req: VesselLocationRequest):
    """Persist current runtime location as part of vessel self-state."""
    from services.vessel_state import set_location

    try:
        state = set_location(
            lat=req.lat,
            lon=req.lon,
            label=req.label,
            source=req.source,
            confidence=req.confidence,
            note=req.note,
            data_dir=DATA_DIR,
        )
        return {"ok": True, "state": state}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/vessel/notes")
async def add_vessel_note(req: VesselNoteRequest):
    """Add a note to the vessel self-journal."""
    from services.vessel_state import add_note

    try:
        state = add_note(title=req.title, body=req.body, kind=req.kind, source=req.source, data_dir=DATA_DIR)
        return {"ok": True, "state": state}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/vessel/notes/{note_id}")
async def delete_vessel_note(note_id: str):
    """Delete a vessel note by id."""
    from services.vessel_state import delete_note

    try:
        state = delete_note(note_id, data_dir=DATA_DIR)
        return {"ok": True, "state": state}
    except KeyError:
        raise HTTPException(404, f"note not found: {note_id}")


@app.post("/api/vessel/calendar/events")
async def add_vessel_calendar_event(req: VesselCalendarEventRequest):
    """Add a local vessel calendar commitment."""
    from services.vessel_state import add_calendar_event

    try:
        state = add_calendar_event(
            title=req.title,
            start=req.start,
            end=req.end,
            location=req.location,
            description=req.description,
            source=req.source,
            data_dir=DATA_DIR,
        )
        return {"ok": True, "state": state}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/world/state")
async def world_state(query: str = ""):
    """Return the deterministic world graph for the current vessel context."""
    from services.computer_tools import TOOL_REGISTRY
    from services.world_simulator import build_world_state

    return {
        "ok": True,
        "world": build_world_state(input_text=query, data_dir=DATA_DIR, tool_names=TOOL_REGISTRY.keys()),
    }


@app.post("/api/world/simulate")
async def world_simulate(req: WorldSimRequest):
    """Run a deterministic world-state scenario comparison."""
    from services.computer_tools import TOOL_REGISTRY
    from services.world_simulator import simulate_world

    return simulate_world(
        input_text=req.input_text,
        horizon=req.horizon,
        data_dir=DATA_DIR,
        tool_names=TOOL_REGISTRY.keys(),
    )


@app.post("/api/world/forecast")
async def world_forecast(req: WorldForecastRequest):
    """Run filtered history/news scenario weighting for future states."""
    from services.world_forecast import forecast_world

    def _as_dict(item):
        if hasattr(item, "model_dump"):
            return item.model_dump()
        return item.dict()

    return forecast_world(
        input_text=req.input_text,
        horizon=req.horizon,
        data_dir=DATA_DIR,
        news_sources=[_as_dict(item) for item in (req.news_sources or [])],
        source_registry=source_registry,
    )


@app.post("/api/world/geotimeline")
async def world_geotimeline(req: WorldGeoTimelineRequest):
    """Return real lat/lon historical anchors, timeline, links, and forecast correction."""
    from services.world_geotimeline import build_geo_timeline
    from services.world_revision_ledger import append_revision, load_revisions

    def _as_dict(item):
        if hasattr(item, "model_dump"):
            return item.model_dump()
        return item.dict()

    news_sources = [_as_dict(item) for item in (req.news_sources or [])]
    live_news = {
        "requested": bool(req.auto_news),
        "fetched_count": 0,
        "coordinate_diversity": 0,
        "engines_used": [],
        "errors": [],
    }
    if req.auto_news and req.input_text.strip():
        try:
            fetched = await browser_node.fetch_with_sources(
                req.input_text.strip(),
                min_sources=req.max_news,
                max_text_chars=5000,
            )
            live_news = {
                "requested": True,
                "fetched_count": int(fetched.get("fetched_count") or 0),
                "coordinate_diversity": int(fetched.get("coordinate_diversity") or 0),
                "engines_used": fetched.get("engines_used") or [],
                "errors": fetched.get("errors") or [],
            }
            news_sources.extend(fetched.get("primary_sources") or [])
        except Exception as exc:
            live_news["errors"] = [f"{type(exc).__name__}: {exc}"]

    deduped_sources = []
    seen_sources = set()
    for source in news_sources:
        key = str(source.get("url") or source.get("title") or "").strip().lower()
        if not key or key in seen_sources:
            continue
        seen_sources.add(key)
        deduped_sources.append(source)

    result = build_geo_timeline(
        input_text=req.input_text,
        horizon=req.horizon,
        data_dir=DATA_DIR,
        news_sources=deduped_sources,
        source_registry=source_registry,
    )
    result["live_news"] = live_news
    if req.persist_revision:
        ledger_path = DATA_DIR / "runtime" / "world_forecast_revisions.jsonl"
        result["revision"] = append_revision(result, path=ledger_path)
        result["revision_history"] = load_revisions(query=req.input_text, path=ledger_path, limit=12)
    else:
        result["revision"] = None
        result["revision_history"] = []
    return result


@app.get("/api/world/revisions")
async def world_revisions(query: str = "", limit: int = 30):
    """Return compact forecast revisions so news-driven corrections remain auditable."""
    from services.world_revision_ledger import load_revisions

    revisions = load_revisions(
        query=query,
        path=DATA_DIR / "runtime" / "world_forecast_revisions.jsonl",
        limit=max(1, min(limit, 300)),
    )
    return {"ok": True, "schema_version": "world_forecast_revision_list.v1", "revisions": revisions}


@app.get("/api/world/trigger")
async def world_trigger(query: str = ""):
    """Expose frontend routing advice for world-view slash/abstract queries."""
    from services.world_simulator import should_trigger_world

    return {"ok": True, "trigger": should_trigger_world(query)}


@app.get("/api/runtime/status")
async def runtime_status(request: Request):
    """Expose the running server identity so UI/debug sessions do not mix ports."""
    latest_plan = None
    try:
        from upgrade_engine import list_plans
        plans = list_plans(1)
        latest_plan = plans[0] if plans else None
    except Exception as e:
        latest_plan = {"error": f"{type(e).__name__}: {e}"}

    relay_apps = []
    relay_error = ""
    try:
        from services.app_controller import list_apps
        relay_apps = list_apps()
    except Exception as e:
        relay_error = f"{type(e).__name__}: {e}"

    try:
        from services.small_task_executor import profile_summary as _small_profile_summary

        small_task = _small_profile_summary(CONFIG_DIR)
    except Exception as e:
        small_task = {"error": f"{type(e).__name__}: {e}"}

    try:
        vessel = summarize_vessel()
    except Exception as e:
        vessel = {"error": f"{type(e).__name__}: {e}"}

    try:
        from services.controller_learning import learning_queue_summary
        controller_learning = learning_queue_summary(APP_ROOT)
    except Exception as e:
        controller_learning = {"error": f"{type(e).__name__}: {e}"}

    try:
        from services.runtime_dependencies import runtime_dependency_status
        dependencies = runtime_dependency_status(APP_ROOT, timeout=0.35)
    except Exception as e:
        dependencies = {"error": f"{type(e).__name__}: {e}"}

    actual_port = request.url.port
    configured_port = int(os.environ.get("URUK_PORT") or actual_port or 8080)
    configured_host = os.environ.get("URUK_HOST", "127.0.0.1")
    return {
        "ok": True,
        "app": "URUK Trinity Console",
        "runtime_identity": {
            "id": RUNTIME_IDENTITY_ID,
            "label": RUNTIME_IDENTITY_LABEL,
            "backend_names_are_identity": False,
        },
        "pid": os.getpid(),
        "run_id": APP_RUN_ID,
        "started_at": APP_STARTED_AT,
        "host": configured_host,
        "request_host": request.url.hostname,
        "port": actual_port,
        "configured_port": configured_port,
        "default_port": 8080,
        "non_default_port": bool(actual_port and actual_port != 8080),
        "entrypoint": str(Path(__file__).resolve()),
        "cwd": str(APP_ROOT.resolve()),
        "code_version": _runtime_code_stamp(),
        "latest_upgrade_plan": latest_plan,
        "loop_state": _upgrade_loop_public_state(),
        "small_task": small_task,
        "controller_learning": controller_learning,
        "dependencies": dependencies,
        "vessel": vessel,
        "provider_health": console.health.snapshot(),
        "provider_health_persistence": console.health.persistence_status(),
        "adaptive_failover": console.adaptive_failover_summary(),
        "active_profiles": console.active_profile_summary(),
        "relay_apps": relay_apps,
        "relay_error": relay_error,
    }


# ─────────────────────────────────────────────────────────────────
# v8.46 — Local LLM Discovery + Direct Chat
# POST /api/local-llm/scan           → probe localhost for LLM apps
# POST /api/local-llm/chat           → direct chat (no Trinity pipeline)
# POST /api/local-llm/add-profile    → inject discovered app as API profile
# ─────────────────────────────────────────────────────────────────

class LocalChatRequest(BaseModel):
    api_base: str
    provider: str
    model: str
    message: str
    system: str = "你係 URUK 協議載體嘅直接回應模式，用廣東話回答。"
    timeout: float = 60.0


class SmallTaskRequest(BaseModel):
    task: str = "classify"
    text: str
    profile: str = "auto"
    options: Dict[str, Any] = Field(default_factory=dict)


class LocalProfileAddRequest(BaseModel):
    profile_name: str          # unique slug e.g. "ollama_llama3"
    app_name: str              # display name e.g. "Ollama"
    provider: str              # "ollama" | "openai"
    api_base: str              # "http://localhost:11434"
    model: str                 # default model
    api_key_env: str = ""      # usually blank for local


@app.post("/api/local-llm/scan")
async def scan_local_llms():
    """Probe localhost ports to discover running local LLM applications."""
    from services.local_llm_discovery import scan as _llm_scan
    import uvicorn as _uv
    # Detect own port (default 8080)
    own_port = int(os.environ.get("URUK_PORT", 8080))
    try:
        apps = await _llm_scan(own_port=own_port)
        return {
            "found": len(apps),
            "apps": [a.to_dict() for a in apps],
        }
    except Exception as e:
        raise HTTPException(500, f"Scan failed: {e}")


@app.get("/api/local-model/routing")
async def local_model_routing():
    """Return task-aware local model assignments and installed-model status."""
    from services.local_model_router import routing_status

    return await routing_status(CONFIG_DIR)


@app.post("/api/local-llm/chat")
async def local_llm_chat(req: LocalChatRequest):
    """Send a message directly to a local LLM app (bypasses Trinity pipeline)."""
    from services.local_llm_discovery import quick_chat as _qchat
    try:
        reply = await _qchat(
            api_base=req.api_base,
            provider=req.provider,
            model=req.model,
            message=req.message,
            system=with_runtime_identity(req.system),
            timeout=req.timeout,
        )
        return {"ok": True, "reply": reply, "model": req.model}
    except httpx.ConnectError:
        raise HTTPException(503, f"Cannot connect to {req.api_base} — is the app running?")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"LLM error: {e}")
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.post("/api/small-task/run")
async def small_task_run(req: SmallTaskRequest):
    """Run a bounded task through the task-aware local worker policy."""
    from services.small_task_executor import run_small_task

    return await run_small_task(
        req.task,
        req.text,
        config_dir=CONFIG_DIR,
        profile_name=req.profile,
        options=req.options,
    )


@app.post("/api/local-llm/add-profile")
async def add_local_llm_profile(req: LocalProfileAddRequest):
    """Inject a discovered local LLM as a named API profile in nodes.yaml."""
    import yaml as _yaml

    cfg_path = CONFIG_DIR / "nodes.yaml"
    if not cfg_path.exists():
        raise HTTPException(404, "nodes.yaml not found")

    raw = cfg_path.read_text(encoding="utf-8")
    data = _yaml.safe_load(raw) or {}
    profiles = data.get("api_profiles") or {}

    slug = req.profile_name.strip().replace(" ", "_").lower()
    if not slug:
        raise HTTPException(400, "profile_name must not be empty")

    profiles[slug] = {
        "provider":      req.provider,
        "api_base":      req.api_base,
        "api_key_env":   req.api_key_env,
        "default_model": req.model,
        "enabled":       True,
    }
    data["api_profiles"] = profiles

    # Atomic write
    tmp = cfg_path.with_suffix(".yaml.tmp")
    tmp.write_text(_yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(cfg_path)

    # Hot-reload console
    console.reload_nodes()

    return {
        "ok": True,
        "profile_name": slug,
        "message": f"Profile '{slug}' added. Now visible in LLM 設定 → API Profiles.",
    }


# ─────────────────────────────────────────────────────────────────
# v8.47b — Desktop App Controller
# GET  /api/app-control/status          → dep check + app list
# POST /api/app-control/install-deps    → pip install pywinauto psutil
# POST /api/app-control/{key}/launch    → launch app
# POST /api/app-control/{key}/send      → send message to app window
# ─────────────────────────────────────────────────────────────────

class AppSendRequest(BaseModel):
    message: str
    new_conversation: bool = False


@app.get("/api/app-control/status")
async def app_control_status():
    """Return dep status + list of known controllable apps."""
    from services.app_controller import get_deps_status, list_apps
    return {
        "deps":  get_deps_status(),
        "apps":  list_apps(),
    }


@app.post("/api/app-control/install-deps")
async def app_control_install_deps():
    """Install pywinauto + psutil in the running Python environment."""
    from services.app_controller import install_deps
    result = await asyncio.to_thread(install_deps)
    if not result["ok"]:
        raise HTTPException(500, result["error"])
    return result


@app.post("/api/app-control/{app_key}/launch")
async def app_control_launch(app_key: str):
    """Launch a known desktop app if it is not already running."""
    from services.app_controller import launch_app
    result = await asyncio.to_thread(launch_app, app_key)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/app-control/{app_key}/send")
async def app_control_send(app_key: str, req: AppSendRequest):
    """Send a message to a running desktop app via UI automation."""
    from services.app_controller import send_to_app
    result = await send_to_app(app_key, req.message, new_conversation=req.new_conversation)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


# ─────────────────────────────────────────────────────────────────
# v8.47 — Claude API Direct Connect
# POST /api/claude/connect   → validate key + save to config/.env
# GET  /api/claude/status    → check if key is configured
# POST /api/claude/chat      → direct chat with Claude (bypasses Trinity)
# ─────────────────────────────────────────────────────────────────

_CLAUDE_KNOWN_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
]


class ClaudeConnectRequest(BaseModel):
    api_key: str
    model: str = "claude-sonnet-4-6"


class ClaudeChatRequest(BaseModel):
    model: str
    message: str
    system: str = "你係 URUK 協議載體嘅直接回應模式，用廣東話回答。"


@app.post("/api/claude/connect")
async def claude_connect(req: ClaudeConnectRequest):
    """Validate an Anthropic API key and persist it to config/.env."""
    import httpx as _httpx

    key = req.api_key.strip()
    if not key:
        raise HTTPException(400, "api_key must not be empty")

    # Lightweight validation — list models (401 = bad key, others = network/plan issues)
    models: list = list(_CLAUDE_KNOWN_MODELS)
    try:
        async with _httpx.AsyncClient(timeout=10.0) as _c:
            _r = await _c.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            )
            if _r.status_code == 401:
                raise HTTPException(401, "API key invalid — Anthropic rejected it.")
            if _r.ok:
                _ids = [m.get("id", "") for m in (_r.json().get("data") or [])]
                if _ids:
                    models = _ids
    except HTTPException:
        raise
    except Exception:
        pass  # Network blip — still save the key

    # Persist to config/.env  (never log full key)
    _env_path = CONFIG_DIR / ".env"
    _lines = _env_path.read_text(encoding="utf-8").splitlines() if _env_path.exists() else []
    _lines = [ln for ln in _lines if not ln.startswith("ANTHROPIC_API_KEY=")]
    _lines.append(f"ANTHROPIC_API_KEY={key}")
    _env_path.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key

    return {
        "ok": True,
        "key_tail": key[-4:],
        "models": models,
    }


@app.get("/api/claude/status")
async def claude_status():
    """Return whether an Anthropic API key is currently configured."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {"configured": False}
    return {"configured": True, "key_tail": key[-4:]}


@app.post("/api/claude/chat")
async def claude_chat_direct(req: ClaudeChatRequest):
    """Direct single-turn chat with Claude (bypasses Trinity pipeline)."""
    from services.local_llm_discovery import quick_chat as _qchat

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise HTTPException(
            400,
            "No Anthropic API key configured. "
            "Go to ⚙ 設定 → 🤖 Claude API 連接 to set it.",
        )
    try:
        reply = await _qchat(
            api_base="https://api.anthropic.com",
            provider="anthropic",
            model=req.model,
            message=req.message,
            system=with_runtime_identity(req.system),
            api_key=key,
        )
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────
# v8.43 — Agent Schedule API
# POST   /api/agent/schedule         → create scheduled run
# GET    /api/agent/schedules        → list all schedules
# DELETE /api/agent/schedule/{id}    → remove schedule
# PATCH  /api/agent/schedule/{id}    → enable / disable
#
# Scheduler backend: APScheduler (optional, degrade gracefully)
#   pip install apscheduler
# Schedules persist to: data/agent_schedules.json
# ─────────────────────────────────────
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler as _APSched
    from apscheduler.triggers.interval import IntervalTrigger as _APInterval
    from apscheduler.triggers.cron import CronTrigger as _APCron
    _APS_OK = True
except ImportError:
    _APSched = None  # type: ignore
    _APS_OK = False

_scheduler_instance = None

def _get_scheduler():
    global _scheduler_instance
    if _scheduler_instance is None and _APS_OK:
        _scheduler_instance = _APSched()
        _scheduler_instance.start()
    return _scheduler_instance


SCHEDULES_PATH = DATA_DIR / "agent_schedules.json"


def _load_schedules() -> dict:
    if SCHEDULES_PATH.exists():
        try:
            return json.loads(SCHEDULES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_schedules(schedules: dict) -> None:
    SCHEDULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_PATH.write_text(json.dumps(schedules, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/schedules")
async def list_schedules():
    return {"schedules": _load_schedules()}


@app.post("/api/schedules")
async def create_schedule(body: dict):
    schedules = _load_schedules()
    schedule_id = body.get("id") or f"sched-{uuid.uuid4().hex[:8]}"
    schedules[schedule_id] = {**body, "id": schedule_id, "run_count": 0,
                               "created_at": datetime.now().isoformat()}
    _save_schedules(schedules)
    return {"ok": True, "id": schedule_id}


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    schedules = _load_schedules()
    if schedule_id not in schedules:
        raise HTTPException(404, "Schedule not found")
    del schedules[schedule_id]
    _save_schedules(schedules)
    return {"ok": True}


def _port_owner_hint(port: int) -> str:
    """Return a short Windows PID hint for an occupied TCP port."""
    if os.name != "nt":
        return ""
    try:
        import subprocess

        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return ""
    needle = f":{int(port)}"
    for line in out.splitlines():
        if needle not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if parts:
            return f" (PID {parts[-1]})"
    return ""


def _preflight_socket_bind(host: str, port: int) -> None:
    """Fail early with a readable launcher message when the port is unavailable."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, int(port)))
    except OSError as exc:
        owner = _port_owner_hint(port)
        print(
            f"URUK launcher: cannot bind {host}:{port}: {exc}",
            file=sys.stderr,
        )
        print(
            f"Port {port} is already unavailable{owner}. "
            f"Open http://127.0.0.1:{port}/ if the server is already running, "
            "or stop that process before starting a new one.",
            file=sys.stderr,
        )
        print(
            "Alternative: run another port with "
            "PowerShell: $env:URUK_PORT='8765'; py app.py",
            file=sys.stderr,
        )
        if host in ("0.0.0.0", "::"):
            print(
                "Local-only fallback: $env:URUK_HOST='127.0.0.1'; py app.py",
                file=sys.stderr,
            )
        raise SystemExit(1)
    finally:
        sock.close()


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("URUK_HOST", "127.0.0.1")
    port = int(os.environ.get("URUK_PORT", "8080"))
    os.environ["URUK_PORT"] = str(port)
    _preflight_socket_bind(host, port)
    # Exclude services/custom_tools/ from hot-reload watch: the upgrade loop
    # installs new tool files there, and WatchFiles would restart the server
    # mid-loop (wiping the in-memory loop state and cancelling the asyncio task).
    # Tool registry hot-reload is handled by POST /api/agent/tool/reload instead.
    # reload_excludes takes relative glob patterns (WatchFiles limitation).
    _reload_excludes = [
        "services/custom_tools/*.py",
        "data/**/*",
        "logs/**/*",
        "_codex_app_*.txt",
        "*.json",
        "*.jsonl",
    ]
    uvicorn.run("app:app", host=host, port=port, reload=True,
                reload_excludes=_reload_excludes)
