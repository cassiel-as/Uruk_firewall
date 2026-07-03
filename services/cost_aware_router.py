"""Cost-aware routing policy for URUK Trinity Console.

This layer decides how far a request should climb before the expensive
reasoning stack is used.  It is deterministic and conservative: if a request
looks like code, self-upgrade, deep Coordinate/Trinity reasoning, or a forced
mode, it keeps the full path available.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Iterable

from services.context_budget import compile_context_budget
from services.coordinate_index import search_coordinate_index
from services.coordinate_knowledge import select_coordinate_cards
from services.kairos_memory import answer_kairos_memory
from services.protocol_concepts import is_protocol_concept_query


_FORCED_MODES = {
    "firewall",
    "blackbox",
    "blackboxlab",
    "scr",
    "news",
    "sovereign",
    "tool_workshop",
    "app_relay",
    "delabel_only",
    "trinity_only",
}

_WORLD_TERMS = (
    "world event",
    "world events",
    "world history",
    "history",
    "news",
    "on this day",
    "world affairs",
    "current events",
    "世界大事",
    "世界事件",
    "世界新聞",
    "國際新聞",
    "國際大事",
    "全球新聞",
    "全球大事",
    "歷史事件",
    "歷史大事",
    "世界大事",
    "世界事件",
    "歷史",
    "新聞",
)

_FRESH_WORLD_TERMS = (
    "today",
    "latest",
    "current",
    "recent",
    "breaking",
    "今日",
    "今天",
    "最新",
    "近期",
    "最近",
    "即時",
)

_LIVE_FRESHNESS_TERMS = (
    "today",
    "latest",
    "current",
    "recent",
    "breaking",
    "now",
    "as of",
    "this week",
    "this month",
    "today is",
    "今日",
    "今天",
    "最近",
    "最新",
    "現時",
    "現在",
    "而家",
    "剛剛",
    "昨日",
    "昨天",
    "近況",
)

_LIVE_PUBLIC_AFFAIRS_TERMS = (
    "world event",
    "world events",
    "world affairs",
    "current events",
    "news",
    "fed",
    "fomc",
    "federal reserve",
    "interest rate",
    "rate decision",
    "central bank",
    "inflation",
    "cpi",
    "jobs report",
    "unemployment",
    "election",
    "war",
    "conflict",
    "tariff",
    "sanction",
    "policy decision",
    "美聯儲",
    "聯儲局",
    "聯準會",
    "利率",
    "議息",
    "息口",
    "減息",
    "加息",
    "央行",
    "通脹",
    "通膨",
    "就業數據",
    "失業率",
    "選舉",
    "戰爭",
    "衝突",
    "關稅",
    "制裁",
    "政策",
    "世界大事",
    "時事",
    "新聞",
)

_LIVE_DATE_RE = re.compile(
    r"(?:20\d{2})\s*(?:[-/年]\s*)\d{1,2}\s*(?:[-/月]\s*)\d{1,2}\s*(?:日)?",
    re.IGNORECASE,
)

_CODE_TERMS = (
    "bug",
    "fix",
    "debug",
    "refactor",
    "test",
    "pytest",
    "javascript",
    "typescript",
    "python",
    "powershell",
    "html",
    "css",
    "api",
    "修",
    "改",
    "測試",
    "代碼",
    "程式",
)

_SELF_UPGRADE_TERMS = (
    "self-upgrade",
    "self upgrade",
    "upgrade report",
    "benchmark",
    "harness",
    "prompt regression",
    "episode compare",
    "自我升級",
    "系統升級",
    "升級報告",
    "基準測試",
    "回歸測試",
    "升級",
    "自我升級",
    "回歸",
    "測試集",
)

_DEEP_TERMS = (
    "trinity",
    "coordinate theory",
    "coordinate",
    "kairos",
    "architecture",
    "design",
    "compare",
    "market",
    "value",
    "三位一體",
    "座標",
    "座標說",
    "設計",
    "市場",
    "價值",
    "深入",
    "分析",
)

_TOOL_TERMS = (
    "open browser",
    "screenshot",
    "click",
    "file",
    "folder",
    "copilot",
    "tool",
    "browser",
    "settings window",
    "open the",
    "瀏覽器",
    "截圖",
    "工具",
    "檔案",
)

_SELF_UPGRADE_EXPLICIT = (
    "self-upgrade",
    "self upgrade",
    "upgrade report",
    "prompt regression",
    "episode compare",
    "自我升級",
    "升級報告",
    "提示詞回歸",
    "對話比較",
)

_SELF_UPGRADE_ACTIONS = (
    "run ",
    "check ",
    "generate ",
    "build ",
    "compare ",
    "audit ",
    "test ",
    "執行",
    "運行",
    "檢查",
    "生成",
    "建立",
    "比較",
    "審計",
    "測試",
    "升級",
)

_DEEP_INTENT_TERMS = (
    "analyse",
    "analyze",
    "evaluate",
    "assess",
    "risk",
    "causal",
    "authority",
    "consequence",
)

_CONTEXT_FOLLOWUP_TERMS = (
    "上一句",
    "上句",
    "上一條",
    "上一個",
    "頭先",
    "剛才",
    "啱啱",
    "本輪對話",
    "今次對話",
    "呢輪對話",
    "當前對話",
    "前面講",
    "之前講",
    "你剛才",
    "你頭先",
    "代表咩",
    "代號",
    "according to the previous",
    "previous message",
    "last message",
    "last turn",
    "earlier in this conversation",
    "this conversation",
)

_BOUNDED_SMALL_PREFIXES = (
    "translate ",
    "convert ",
    "rewrite ",
    "calculate ",
    "return this ",
    "put these ",
    "list monday",
    "change the sentence ",
    "shorten this sentence ",
)

_BOUNDED_SMALL_WRAPPERS = (
    "please answer this briefly and directly:",
    "give a concise response to this request:",
    "quick question:",
    "please respond directly:",
    "answer briefly:",
    "please ",
    "kindly ",
)

_EARLY_BOUNDED_SMALL_PREFIXES = (
    "translate ",
    "convert ",
    "calculate ",
    "return this ",
    "put these ",
    "list monday",
    "change the sentence ",
    "shorten this sentence ",
)

_DATE_RE = re.compile(r"(20\d{2})[-/年\s]+0?\d{1,2}[-/月\s]+0?\d{1,2}|(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*(?:日|號)?")


# ── De-labeling signal expansion ──────────────────────────────────────────
# 母體標籤 query（"失敗者" / "孤獨"）本身唔 match 用物理詞彙寫嘅座標卡，會被
# under-route 去 small_task，攞唔到佢最需要嘅去標籤化（座標/Trinity 深層路徑）。
# 呢度用 DELABELING_MATRIX 做平、確定性嘅 label→physical 信號擴展，等座標匹配
# 可以 fire。ADDITIVE：只會令路由更深，唔會令任何 query 變淺。
_DELABEL_MIN_LABEL_LEN = 2     # 跳過單字標籤（病/老/死/餓…）避免 over-trigger
_DELABEL_MAX_QUERY_LEN = 120   # 只擴展短 query（標籤係主題，唔係長任務句裡偶然出現）


@functools.lru_cache(maxsize=8)
def _load_delabel_pairs(matrix_path_str: str) -> tuple[tuple[str, str], ...]:
    """Parse DELABELING_MATRIX.md tables → ((label, physical), …). Cached by path."""
    try:
        lines = Path(matrix_path_str).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    out: list[tuple[str, str]] = []
    for line in lines:
        match = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if not match:
            continue
        label, physical = match.group(1).strip(), match.group(2).strip()
        if not label or "母體" in label or set(label) <= set("-: "):
            continue
        if len(label) < _DELABEL_MIN_LABEL_LEN:
            continue
        out.append((label, physical))
    return tuple(out)


def _delabel_expansion(query: str, root: Path) -> str:
    """Return physical reductions of any 母體 labels present in a short query."""
    if not query or len(query) > _DELABEL_MAX_QUERY_LEN:
        return ""
    pairs = _load_delabel_pairs(str(Path(root) / "data" / "protocol" / "DELABELING_MATRIX.md"))
    found = [physical for label, physical in pairs if label and label in query]
    return " ".join(found)


def route_query(
    query: str,
    *,
    root: Path,
    in_session_history: Iterable[Any] | None = None,
    selected_modes: Iterable[Any] | None = None,
    pipeline_mode: str | None = "auto",
    refs: list[str] | None = None,
) -> dict[str, Any]:
    """Return deterministic route, budget, and estimated model-call telemetry."""
    query = str(query or "")
    lower = query.casefold()
    selected = _selected_mode_names(selected_modes)
    pipeline_mode = (pipeline_mode or "auto").strip() or "auto"

    forced = _forced_mode(pipeline_mode, selected)
    if not forced and _is_unambiguous_bounded_small_request(lower):
        return _decision(
            query,
            route_kind="small_task",
            model_tier="small_local",
            escalation_level=1,
            estimated_model_calls=1,
            estimated_api_model_calls=0,
            reason="Explicit bounded text transformation takes priority over quoted subject terms",
            refs=refs,
            recommended_pipeline_mode="auto",
        )
    if not forced or forced == "trinity_only" or pipeline_mode == "plain_llm":
        kairos_direct = answer_kairos_memory(query, Path(root), history=in_session_history)
        if kairos_direct:
            direct_short_circuit = "kairos_memory_direct"
            direct_mode = "kairos_memory_direct"
            direct_reason = "Kairos/index answer matched before model generation"
            if "Kairos candidate" in kairos_direct and "世界大事" in kairos_direct:
                direct_short_circuit = "date_scope_clarification"
                direct_mode = "date_scope_clarification"
                direct_reason = "Ambiguous date query needs scope clarification before memory/news lookup"
            return _decision(
                query,
                route_kind="deterministic_memory",
                model_tier="deterministic",
                escalation_level=0,
                estimated_model_calls=0,
                estimated_api_model_calls=0,
                reason=direct_reason,
                refs=[
                    "data/kairos/KAIROS_MEMORY_INDEX.json",
                    "data/kairos/KAIROS_ACTIVE.md",
                    "data/kairos/KAIROS_ARCHIVE_INDEX.md",
                ],
                short_circuit=direct_short_circuit,
                direct_answer=kairos_direct,
                recommended_pipeline_mode=direct_mode,
                suppress_density_proposal=True,
            )

    if forced:
        return _decision(
            query,
            route_kind="forced",
            model_tier="forced_pipeline",
            escalation_level=3,
            estimated_model_calls=8,
            estimated_api_model_calls=8,
            reason=f"Forced pipeline mode: {forced}",
            refs=refs,
            recommended_pipeline_mode=pipeline_mode,
            skip_pre_gate=True,
        )

    if _needs_live_world_sources(query):
        return _decision(
            query,
            route_kind="world_query",
            model_tier="tool_or_search",
            escalation_level=1,
            estimated_model_calls=1,
            estimated_api_model_calls=0,
            reason="Fresh/current public-affairs query requires BrowserNode grounding before analysis",
            refs=refs,
            recommended_pipeline_mode="news",
        )

    if _is_self_upgrade_request(lower):
        return _decision(
            query,
            route_kind="self_upgrade",
            model_tier="desktop_or_strong",
            escalation_level=3,
            estimated_model_calls=2,
            estimated_api_model_calls=0,
            reason="Self-upgrade/harness request should use tool-backed strong worker",
            refs=refs,
            recommended_pipeline_mode="auto",
            skip_pre_gate=True,
        )

    if _contains_any(lower, _CODE_TERMS):
        return _decision(
            query,
            route_kind="code_task",
            model_tier="codex_or_desktop",
            escalation_level=2,
            estimated_model_calls=1,
            estimated_api_model_calls=0,
            reason="Code/debug/edit request should be handled by tool-backed coder",
            refs=refs,
            recommended_pipeline_mode="auto",
            skip_pre_gate=True,
        )

    recent_inputs = _recent_history_inputs(in_session_history, limit=2)
    protocol_concept = is_protocol_concept_query(query) or (
        any(is_protocol_concept_query(item) for item in recent_inputs)
        and _is_protocol_followup(query)
    )
    # De-label expansion: let coordinate cards match raw-label input (e.g. "失敗者"
    # → "當前能量輸出低於系統要求") so 母體-labeled queries are not under-routed.
    _expansion = _delabel_expansion(query, Path(root))
    _coord_query = f"{query} {_expansion}" if _expansion else query
    coord_hits = search_coordinate_index(Path(root), _coord_query, limit=4)
    explicit_coord_hits = select_coordinate_cards(_coord_query, max_cards=4, root=Path(root))
    if protocol_concept:
        return _decision(
            query,
            route_kind="deep_reasoning",
            model_tier="strong_reasoning",
            escalation_level=2,
            estimated_model_calls=2,
            estimated_api_model_calls=2,
            reason="Core abstract/protocol concept requires Coordinate/Trinity path",
            refs=[
                "data/theory/COORDINATE_INDEX.json",
                "data/theory/COORDINATE_KNOWLEDGE_CARDS.md",
                "data/theory/座標說_v5_updated.md",
                "config/prompts/_canonical_anchor.txt",
            ],
            coordinate_hits=[_compact_coord_hit(hit) for hit in coord_hits],
            recommended_pipeline_mode="protocol_compact",
            skip_pre_gate=True,
        )

    if _is_context_followup(query):
        return _decision(
            query,
            route_kind="deep_reasoning",
            model_tier="strong_reasoning",
            escalation_level=2,
            estimated_model_calls=2,
            estimated_api_model_calls=2,
            reason="Context-dependent follow-up requires in-session history",
            refs=refs,
            recommended_pipeline_mode="auto",
            skip_pre_gate=True,
        )

    if _is_bounded_small_request(lower):
        return _decision(
            query,
            route_kind="small_task",
            model_tier="small_local",
            escalation_level=1,
            estimated_model_calls=1,
            estimated_api_model_calls=0,
            reason="Bounded formatting, conversion, or transformation task",
            refs=refs,
            recommended_pipeline_mode="auto",
        )

    if _contains_any(lower, _DEEP_INTENT_TERMS):
        return _decision(
            query,
            route_kind="deep_reasoning",
            model_tier="strong_reasoning",
            escalation_level=2,
            estimated_model_calls=4,
            estimated_api_model_calls=4,
            reason="Explicit analysis, risk, or authority reasoning request",
            refs=refs,
            recommended_pipeline_mode="auto",
            skip_pre_gate=True,
        )

    # An explicit operation remains a tool task even when an execution-boundary
    # Coordinate card also matches. The card can still validate the tool output.
    if _contains_any(lower, _TOOL_TERMS):
        return _decision(
            query,
            route_kind="tool_task",
            model_tier="tool_router",
            escalation_level=2,
            estimated_model_calls=1,
            estimated_api_model_calls=0,
            reason="Tool or desktop context likely needed",
            refs=refs,
            recommended_pipeline_mode="auto",
        )

    if explicit_coord_hits and len(query) <= 260:
        return _decision(
            query,
            route_kind="deep_reasoning",
            model_tier="strong_reasoning",
            escalation_level=2,
            estimated_model_calls=4,
            estimated_api_model_calls=4,
            reason="Coordinate cards matched; use theory as output self-check",
            refs=["data/theory/COORDINATE_INDEX.json", "data/theory/COORDINATE_KNOWLEDGE_CARDS.md"],
            coordinate_hits=[_compact_coord_hit(hit) for hit in explicit_coord_hits],
            recommended_pipeline_mode="auto",
            skip_pre_gate=True,
        )

    if _contains_any(lower, _DEEP_TERMS) or len(query) >= 350:
        return _decision(
            query,
            route_kind="deep_reasoning",
            model_tier="strong_reasoning",
            escalation_level=2,
            estimated_model_calls=4,
            estimated_api_model_calls=4,
            reason="Deep reasoning or URUK knowledge request",
            refs=refs,
            recommended_pipeline_mode="auto",
            skip_pre_gate=True,
        )

    return _decision(
        query,
        route_kind="small_task",
        model_tier="small_local",
        escalation_level=1,
        estimated_model_calls=1,
        estimated_api_model_calls=0,
        reason="Short ordinary request can be tried by small/pre-gate path first",
        refs=refs,
        recommended_pipeline_mode="auto",
    )


def _decision(
    query: str,
    *,
    route_kind: str,
    model_tier: str,
    escalation_level: int,
    estimated_model_calls: int,
    estimated_api_model_calls: int,
    reason: str,
    refs: list[str] | None = None,
    recommended_pipeline_mode: str = "auto",
    short_circuit: str | None = None,
    direct_answer: str | None = None,
    skip_pre_gate: bool = False,
    suppress_density_proposal: bool = False,
    coordinate_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context_budget = compile_context_budget(
        query,
        route_kind=route_kind,
        refs=refs or [],
        history_turns=0,
        extra={"coordinate_hits": coordinate_hits or []},
    )
    cost_metrics = {
        "route_kind": route_kind,
        "tier": model_tier,
        "estimated_model_calls": int(estimated_model_calls),
        "estimated_api_model_calls": int(estimated_api_model_calls),
        "estimated_context_tokens": int(context_budget.get("estimated_total_tokens") or 0),
        "estimated_cost_class": _cost_class(route_kind, model_tier, estimated_model_calls, estimated_api_model_calls),
    }
    return {
        "route_kind": route_kind,
        "model_tier": model_tier,
        "escalation_level": int(escalation_level),
        "reason": reason,
        "short_circuit": short_circuit,
        "direct_answer": direct_answer,
        "recommended_pipeline_mode": recommended_pipeline_mode,
        "skip_pre_gate": bool(skip_pre_gate),
        "suppress_density_proposal": bool(suppress_density_proposal),
        "coordinate_hits": coordinate_hits or [],
        "context_budget": context_budget,
        "cost_metrics": cost_metrics,
    }


def _cost_class(route_kind: str, model_tier: str, model_calls: int, api_calls: int) -> str:
    if model_calls <= 0 or route_kind.startswith("deterministic"):
        return "zero"
    if api_calls <= 0 and model_calls <= 1:
        return "low"
    if api_calls <= 1 and model_calls <= 2:
        return "medium"
    if "strong" in model_tier or api_calls >= 3 or model_calls >= 4:
        return "high"
    return "medium"


def _selected_mode_names(selected_modes: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    for item in selected_modes or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(str(item.get("mode") or ""))
        else:
            out.append(str(getattr(item, "mode", "") or ""))
    return [name for name in out if name]


def _recent_history_inputs(history: Iterable[Any] | None, limit: int = 2) -> list[str]:
    items = list(history or [])[-max(1, int(limit)):]
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            value = item.get("input") or item.get("user") or ""
        else:
            value = getattr(item, "input", "") or getattr(item, "user", "")
        if str(value).strip():
            out.append(str(value))
    return out


def _is_protocol_followup(query: str) -> bool:
    text = str(query or "").strip().casefold()
    if not text or len(text) > 500:
        return False
    markers = (
        "呢個", "呢啲", "佢", "又係", "有咩關係", "同 ", "咁 ",
        "嚴格", "推導", "比喻", "定係", "點解", "即係", "是否",
        "this", "that", "it ", "strict", "derive", "derivation",
        "metaphor", "analogy", "relationship", "how does", "why ",
    )
    return any(marker in text for marker in markers)


def _forced_mode(pipeline_mode: str, selected: list[str]) -> str | None:
    if pipeline_mode in _FORCED_MODES:
        return pipeline_mode
    non_auto = [mode for mode in selected if mode and mode != "auto"]
    if non_auto:
        return ",".join(non_auto)
    return None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        needle = term.casefold()
        if not needle:
            continue
        if re.fullmatch(r"[a-z0-9_+#.-]{1,4}", needle):
            if re.search(rf"(?<![a-z0-9_+#.-]){re.escape(needle)}(?![a-z0-9_+#.-])", text):
                return True
            continue
        if needle in text:
            return True
    return False


def _is_context_followup(query: str) -> bool:
    lower = str(query or "").casefold()
    return _contains_any(lower, _CONTEXT_FOLLOWUP_TERMS)


def _is_bounded_small_request(text: str) -> bool:
    value = str(text or "").strip()
    for _ in range(4):
        wrapper = next((item for item in _BOUNDED_SMALL_WRAPPERS if value.startswith(item)), "")
        if not wrapper:
            break
        value = value[len(wrapper):].lstrip()
    return value.startswith(_BOUNDED_SMALL_PREFIXES)


def _is_unambiguous_bounded_small_request(text: str) -> bool:
    value = str(text or "").strip()
    for _ in range(4):
        wrapper = next((item for item in _BOUNDED_SMALL_WRAPPERS if value.startswith(item)), "")
        if not wrapper:
            break
        value = value[len(wrapper):].lstrip()
    if value.startswith(_EARLY_BOUNDED_SMALL_PREFIXES):
        return True
    if not value.startswith("rewrite "):
        return False
    return _contains_any(
        value,
        (
            "lowercase",
            "uppercase",
            "title case",
            "sentence",
            "phrase",
            "wording",
            "comma-separated",
            "comma separated",
        ),
    )


def _needs_live_world_sources(query: str) -> bool:
    text = str(query or "")
    lower = text.casefold()
    has_legacy_world = _contains_any(lower, _WORLD_TERMS)
    has_freshness = (
        _contains_any(lower, _FRESH_WORLD_TERMS)
        or _contains_any(lower, _LIVE_FRESHNESS_TERMS)
    )
    has_public_affairs = (
        has_legacy_world
        