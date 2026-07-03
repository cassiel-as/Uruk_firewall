"""Context budget compiler for URUK runtime routing.

The runtime should not send the same context payload to every path.  This
module gives deterministic routes a zero/low budget, small tasks a compact
budget, and full Trinity/code-upgrade tasks enough room to work.
"""

from __future__ import annotations

from typing import Any, Mapping


ROUTE_CONTEXT_LIMITS: dict[str, int] = {
    "deterministic_memory": 0,
    "deterministic_coordinate": 600,
    "cache_hit": 0,
    "ordinary_qna": 900,
    "small_task": 900,
    "world_query": 1800,
    "tool_task": 1400,
    "code_task": 6000,
    "self_upgrade": 9000,
    "deep_reasoning": 8000,
    "full_trinity": 8000,
    "forced": 8000,
}


SOURCE_LIMITS: dict[str, dict[str, int]] = {
    "deterministic_memory": {"history_turns": 0, "rag_hits": 0, "coordinate_cards": 0},
    "deterministic_coordinate": {"history_turns": 0, "rag_hits": 0, "coordinate_cards": 4},
    "cache_hit": {"history_turns": 0, "rag_hits": 0, "coordinate_cards": 0},
    "ordinary_qna": {"history_turns": 2, "rag_hits": 0, "coordinate_cards": 0},
    "small_task": {"history_turns": 2, "rag_hits": 0, "coordinate_cards": 0},
    "world_query": {"history_turns": 1, "rag_hits": 0, "coordinate_cards": 0, "source_limit": 5},
    "tool_task": {"history_turns": 2, "rag_hits": 2, "coordinate_cards": 1},
    "code_task": {"history_turns": 4, "rag_hits": 4, "coordinate_cards": 2},
    "self_upgrade": {"history_turns": 6, "rag_hits": 6, "coordinate_cards": 4},
    "deep_reasoning": {"history_turns": 4, "rag_hits": 6, "coordinate_cards": 4},
    "full_trinity": {"history_turns": 4, "rag_hits": 6, "coordinate_cards": 4},
    "forced": {"history_turns": 4, "rag_hits": 6, "coordinate_cards": 4},
}


def estimate_tokens(value: Any) -> int:
    """Cheap token estimate used for budgeting and UI telemetry."""
    text = "" if value is None else str(value)
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def compile_context_budget(
    query: Any,
    *,
    route_kind: str,
    refs: list[str] | None = None,
    history_turns: int = 0,
    max_context_tokens: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded context budget plan for one runtime route."""
    route_kind = str(route_kind or "full_trinity")
    refs = list(refs or [])
    extra = dict(extra or {})

    default_limit = ROUTE_CONTEXT_LIMITS.get(route_kind, ROUTE_CONTEXT_LIMITS["full_trinity"])
    limit = int(max_context_tokens or default_limit)
    estimated_input_tokens = estimate_tokens(query)
    estimated_refs_tokens = estimate_tokens("\n".join(refs))
    estimated_extra_tokens = estimate_tokens(extra)
    estimated_total = estimated_input_tokens + estimated_refs_tokens + estimated_extra_tokens

    warnings: list[str] = []
    if estimated_total > limit and limit > 0:
        warnings.append("context_over_budget")
    if route_kind.startswith("deterministic") and history_turns:
        warnings.append("history_ignored_for_deterministic_route")

    if limit <= 0:
        strategy = "no_context"
        status = "ok"
    elif estimated_total <= limit:
        strategy = "fit"
        status = "ok"
    else:
        strategy = "truncate_by_source_limits"
        status = "over_budget"

    source_limits = dict(SOURCE_LIMITS.get(route_kind, SOURCE_LIMITS["full_trinity"]))
    if history_turns:
        source_limits["requested_history_turns"] = int(history_turns)

    return {
        "route_kind": route_kind,
        "max_context_tokens": limit,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_refs_tokens": estimated_refs_tokens,
        "estimated_extra_tokens": estimated_extra_tokens,
        "estimated_total_tokens": estimated_total,
        "strategy": strategy,
        "status": status,
        "source_limits": source_limits,
        "warnings": warnings,
    }
