"""Best-effort shadow comparison for the trained URUK controller.

The shadow can observe and log disagreements. It cannot change routing or
grant tool authority.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from services.controller_policy import compile_controller_decision, compile_controller_example_input
from services.controller_learning import accumulate_learning_candidate
from training.dataset_validator import validate_controller_decision


DEFAULT_CONFIG = {
    "enabled": False,
    "url": "http://127.0.0.1:8766",
    "timeout_seconds": 30.0,
    "max_pending": 2,
    "log_query_preview": False,
    "learning_queue_enabled": False,
    "agreement_sample_rate": 0.1,
    "max_records_per_day": 500,
}
_TASKS: set[asyncio.Task[Any]] = set()
GUARDED_FIELDS = (
    "pipeline",
    "knowledge_layers",
    "task_profile",
    "model_budget",
    "tool_permission",
    "escalation_required",
    "confidence",
    "reason_codes",
)


def _finish_task(task: asyncio.Task[Any]) -> None:
    _TASKS.discard(task)
    try:
        task.result()
    except Exception:
        # Shadow failures must never affect or warn through the production route.
        pass


def load_shadow_config(root: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    path = Path(root) / "config" / "controller_shadow.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            config.update(value)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return config


def compare_decisions(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    tracked = (
        "route_kind",
        "pipeline",
        "knowledge_layers",
        "task_profile",
        "model_budget",
        "tool_permission",
        "escalation_required",
    )
    differences = {
        key: {"reference": reference.get(key), "candidate": candidate.get(key)}
        for key in tracked
        if reference.get(key) != candidate.get(key)
    }
    schema_errors = validate_controller_decision(candidate)
    return {
        "schema_valid": not schema_errors,
        "schema_errors": schema_errors,
        "route_match": reference.get("route_kind") == candidate.get("route_kind"),
        "authority_match": reference.get("tool_permission") == candidate.get("tool_permission"),
        "escalation_match": reference.get("escalation_required") == candidate.get("escalation_required"),
        "exact_match": reference == candidate,
        "differences": differences,
    }


def guard_controller_candidate(
    reference: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Accept only a valid matching route; compile every policy field deterministically."""
    schema_errors = validate_controller_decision(candidate)
    route_match = candidate.get("route_kind") == reference.get("route_kind")
    if schema_errors or not route_match:
        reason = "schema_invalid" if schema_errors else "route_mismatch"
        return dict(reference), {
            "schema_version": "uruk_controller_authority_guard.v1",
            "route_accepted": False,
            "fallback_used": True,
            "fallback_reason": reason,
            "schema_errors": schema_errors,
            "overridden_fields": sorted(GUARDED_FIELDS),
            "authority_source": "deterministic_reference",
        }

    guarded = dict(candidate)
    overridden: list[str] = []
    for key in GUARDED_FIELDS:
        if guarded.get(key) != reference.get(key):
            overridden.append(key)
        guarded[key] = reference.get(key)
    guarded["schema_version"] = reference.get("schema_version")
    return guarded, {
        "schema_version": "uruk_controller_authority_guard.v1",
        "route_accepted": True,
        "fallback_used": False,
        "fallback_reason": "",
        "schema_errors": [],
        "overridden_fields": sorted(overridden),
        "authority_source": "deterministic_reference",
    }


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/predict",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def run_shadow_once(
    query: str,
    *,
    root: Path,
    pipeline_mode: str = "auto",
    selected_modes: Iterable[Any] | None = None,
) -> dict[str, Any]:
    config = load_shadow_config(root)
    if not config.get("enabled"):
        return {"status": "disabled"}
    reference = compile_controller_decision(
        query,
        root=Path(root),
        pipeline_mode=pipeline_mode,
        selected_modes=selected_modes,
    )
    model_input = compile_controller_example_input(
        query,
        root=Path(root),
        pipeline_mode=pipeline_mode,
        selected_modes=selected_modes,
    )
    payload = _post_json(str(config["url"]), {"input": model_input}, float(config["timeout_seconds"]))
    candidate = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    comparison = compare_decisions(reference, candidate)
    guarded_candidate, authority_guard = guard_controller_candidate(reference, candidate)
    guarded_comparison = compare_decisions(reference, guarded_candidate)
    record = {
        "schema_version": "uruk_controller_shadow.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query_sha256": hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest(),
        "query_preview": query[:160] if config.get("log_query_preview") else None,
        "reference": reference,
        "candidate": candidate,
        "comparison": comparison,
        "guarded_candidate": guarded_candidate,
        "guarded_comparison": guarded_comparison,
        "authority_guard": authority_guard,
        "candidate_latency_ms": payload.get("latency_ms"),
        "authority": "shadow_only",
    }
    try:
        record["learning_queue"] = accumulate_learning_candidate(
            query,
            root=Path(root),
            model_input=model_input,
            reference=reference,
            candidate=candidate,
            comparison=comparison,
            config=config,
        )
    except Exception as exc:
        record["learning_queue"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    log_dir = Path(root) / "data" / "controller_shadow"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return record


def schedule_controller_shadow(
    query: str,
    *,
    root: Path,
    pipeline_mode: str = "auto",
    selected_modes: Iterable[Any] | None = None,
) -> bool:
    config = load_shadow_config(root)
    if not config.get("enabled"):
        return False
    if len(_TASKS) >= max(1, int(config.get("max_pending") or 2)):
        return False
    task = asyncio.create_task(asyncio.to_thread(
        run_shadow_once,
        query,
        root=Path(root),
        pipeline_mode=pipeline_mode,
        selected_modes=list(selected_modes or []),
    ))
    _TASKS.add(task)
    task.add_done_callback(_finish_task)
    return True
