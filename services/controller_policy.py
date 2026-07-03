"""Strict controller decisions for routing-model training and shadow evaluation.

The controller chooses how URUK should process a request. It never writes the
final answer and never grants itself execution authority.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from services.cost_aware_router import route_query
from services.protocol_concepts import is_protocol_concept_query


CONTROLLER_SCHEMA_VERSION = "uruk_controller_decision.v1"

ROUTE_KINDS = frozenset({
    "deterministic_memory",
    "world_query",
    "self_upgrade",
    "code_task",
    "deep_reasoning",
    "tool_task",
    "small_task",
    "forced",
})

TASK_PROFILES = frozenset({
    "deterministic",
    "auto",
    "local_language",
    "deep_reasoning",
    "code_coworker",
    "upgrade",
    "api_reasoning",
    "windows_copilot",
})

KNOWLEDGE_LAYERS = frozenset({
    "kairos",
    "theory",
    "protocol",
    "runtime",
    "harness",
    "external_current",
})

TOOL_PERMISSIONS = frozenset({
    "none",
    "read_only",
    "search_read",
    "workspace_write_reviewed",
    "system_change_reviewed",
    "operator_confirmed_hardware",
})


def _selected_mode_names(selected_modes: Iterable[Any] | None) -> list[str]:
    names: list[str] = []
    for item in selected_modes or []:
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            value = str(item.get("mode") or "")
        else:
            value = str(getattr(item, "mode", "") or "")
        if value:
            names.append(value)
    return names


def build_controller_signals(
    query: str,
    route: dict[str, Any],
    *,
    pipeline_mode: str = "auto",
    selected_modes: Iterable[Any] | None = None,
    available_capabilities: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build bounded runtime signals without including answers or private context."""
    coordinate_ids = sorted({
        str(hit.get("id"))
        for hit in (route.get("coordinate_hits") or [])
        if isinstance(hit, dict) and hit.get("id")
    })
    route_kind = str(route.get("route_kind") or "")
    cost = route.get("cost_metrics") or {}
    context = route.get("context_budget") or {}
    return {
        "schema_version": "uruk_controller_signals.v1",
        "text_length": len(str(query or "")),
        "pipeline_mode": str(pipeline_mode or "auto"),
        "selected_modes": _selected_mode_names(selected_modes),
        "available_capabilities": sorted({str(item) for item in (available_capabilities or []) if item}),
        "protocol_concept_detected": bool(is_protocol_concept_query(query)),
        "coordinate_card_ids": coordinate_ids,
        "kairos_memory_match": route_kind == "deterministic_memory",
        "fresh_external_evidence_required": route_kind == "world_query",
        "forced_mode_requested": route_kind == "forced",
        "estimated_context_tokens": int(context.get("estimated_total_tokens") or 0),
        "estimated_model_calls": int(cost.get("estimated_model_calls") or 0),
    }


def _knowledge_layers(route_kind: str, route: dict[str, Any], protocol_concept: bool) -> list[str]:
    if route_kind == "deterministic_memory":
        return ["kairos"]
    if route_kind == "world_query":
        return ["external_current"]
    if route_kind == "self_upgrade":
        return ["runtime", "harness"]
    if route_kind in {"code_task", "tool_task"}:
        return ["runtime"]
    if route_kind == "deep_reasoning":
        layers: list[str] = []
        if protocol_concept:
            layers.extend(["theory", "protocol"])
        elif route.get("coordinate_hits"):
            layers.append("theory")
        return layers
    if route_kind == "forced":
        mode = str(route.get("recommended_pipeline_mode") or "")
        if mode == "news":
            return ["external_current"]
        if mode in {"firewall", "blackbox", "blackboxlab", "scr", "sovereign", "trinity_only"}:
            return ["theory", "protocol"]
        if mode in {"tool_workshop", "app_relay"}:
            return ["runtime"]
    return []


def _task_profile(route_kind: str, query: str) -> str:
    if route_kind == "deterministic_memory":
        return "deterministic"
    if route_kind == "world_query":
        return "api_reasoning"
    if route_kind == "self_upgrade":
        return "upgrade"
    if route_kind == "code_task":
        return "code_coworker"
    if route_kind == "deep_reasoning":
        return "deep_reasoning"
    if route_kind == "tool_task":
        lower = str(query or "").casefold()
        if any(term in lower for term in ("windows", "copilot", "taskbar", "start menu", "onedrive")):
            return "windows_copilot"
        return "auto"
    if route_kind == "small_task":
        return "local_language"
    return "auto"


def _tool_permission(route_kind: str, route: dict[str, Any]) -> str:
    if route_kind == "forced":
        mode = str(route.get("recommended_pipeline_mode") or "")
        if mode == "news":
            return "search_read"
        if mode == "tool_workshop":
            return "workspace_write_reviewed"
        if mode == "app_relay":
            return "read_only"
        return "none"
    return {
        "world_query": "search_read",
        "self_upgrade": "system_change_reviewed",
        "code_task": "workspace_write_reviewed",
        "tool_task": "read_only",
    }.get(route_kind, "none")


def _confidence(route_kind: str, protocol_concept: bool, route: dict[str, Any]) -> float:
    if route_kind in {"deterministic_memory", "forced"}:
        return 1.0
    if route_kind in {"self_upgrade", "code_task", "world_query"}:
        return 0.98
    if route_kind == "deep_reasoning":
        return 0.98 if protocol_concept or route.get("coordinate_hits") else 0.88
    if route_kind == "tool_task":
        return 0.9
    return 0.82


def _reason_codes(route_kind: str, protocol_concept: bool, route: dict[str, Any]) -> list[str]:
    codes = [f"route.{route_kind}"]
    if protocol_concept:
        codes.append("signal.protocol_concept")
    if route.get("coordinate_hits"):
        codes.append("signal.coordinate_card_match")
    if route_kind == "deterministic_memory":
        codes.extend(["signal.kairos_index_match", "policy.zero_model_path"])
    elif route_kind == "world_query":
        codes.append("policy.fresh_external_evidence")
    elif route_kind in {"self_upgrade", "code_task", "tool_task", "forced"}:
        codes.append("policy.tool_authority_required")
    elif route_kind == "deep_reasoning":
        codes.append("policy.strong_reasoning_required")
    elif route_kind == "small_task":
        codes.append("policy.local_worker_allowed")
    return codes


def compile_controller_decision(
    query: str,
    *,
    root: Path,
    pipeline_mode: str = "auto",
    selected_modes: Iterable[Any] | None = None,
    in_session_history: Iterable[Any] | None = None,
    refs: list[str] | None = None,
) -> dict[str, Any]:
    """Compile the reference controller output from the deterministic router."""
    route = route_query(
        query,
        root=Path(root),
        in_session_history=in_session_history,
        selected_modes=selected_modes,
        pipeline_mode=pipeline_mode,
        refs=refs,
    )
    route_kind = str(route.get("route_kind") or "small_task")
    protocol_concept = bool(is_protocol_concept_query(query))
    estimated_calls = int(((route.get("cost_metrics") or {}).get("estimated_model_calls") or 0))
    pipeline = str(route.get("recommended_pipeline_mode") or pipeline_mode or "auto")
    if route_kind == "forced" and pipeline == "auto":
        forced_modes = [name for name in _selected_mode_names(selected_modes) if name != "auto"]
        if forced_modes:
            pipeline = ",".join(forced_modes)
    return {
        "schema_version": CONTROLLER_SCHEMA_VERSION,
        "route_kind": route_kind,
        "pipeline": pipeline,
        "knowledge_layers": _knowledge_layers(route_kind, route, protocol_concept),
        "task_profile": _task_profile(route_kind, query),
        "model_budget": max(0, min(12, estimated_calls)),
        "tool_permission": _tool_permission(route_kind, route),
        "escalation_required": route_kind not in {"deterministic_memory", "small_task"},
        "confidence": _confidence(route_kind, protocol_concept, route),
        "reason_codes": _reason_codes(route_kind, protocol_concept, route),
    }


def compile_controller_example_input(
    query: str,
    *,
    root: Path,
    pipeline_mode: str = "auto",
    selected_modes: Iterable[Any] | None = None,
    available_capabilities: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build the model-facing input and deterministic helper signals."""
    route = route_query(
        query,
        root=Path(root),
        selected_modes=selected_modes,
        pipeline_mode=pipeline_mode,
    )
    return {
        "user_input": str(query or ""),
        "runtime_signals": build_controller_signals(
            query,
            route,
            pipeline_mode=pipeline_mode,
            selected_modes=selected_modes,
            available_capabilities=available_capabilities,
        ),
    }
