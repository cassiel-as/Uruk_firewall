"""Deterministic stability golden-case runner for URUK.

The coordinate benchmark checks theory-card selection and output evaluation.
This runner checks runtime contracts that must stay stable across upgrades:
routing, Kairos disambiguation, world-simulation triggers, and identity guards.
It deliberately does not call an LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "data" / "benchmarks" / "stability_golden_cases.json"


def _contains(text: Any, needle: Any) -> bool:
    return str(needle or "").casefold() in str(text or "").casefold()


def _subset(expected: Iterable[Any], actual: Iterable[Any]) -> bool:
    return {str(x) for x in expected or []}.issubset({str(x) for x in actual or []})


def _value_at(payload: Dict[str, Any], dotted: str) -> Any:
    cur: Any = payload
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _check_equal(checks: List[Dict[str, Any]], name: str, actual: Any, expected: Any) -> None:
    checks.append({
        "name": name,
        "passed": actual == expected,
        "expected": expected,
        "actual": actual,
    })


def _check_true(checks: List[Dict[str, Any]], name: str, value: Any) -> None:
    checks.append({"name": name, "passed": bool(value), "actual": value})


def _check_false(checks: List[Dict[str, Any]], name: str, value: Any) -> None:
    checks.append({"name": name, "passed": not bool(value), "actual": value})


def _run_route_case(case: Dict[str, Any], *, root: Path) -> Dict[str, Any]:
    from services.cost_aware_router import route_query

    route = route_query(case.get("input", ""), root=root)
    expect = case.get("expect") or {}
    checks: List[Dict[str, Any]] = []

    for key in ("route_kind", "short_circuit", "recommended_pipeline_mode", "model_tier"):
        if key in expect:
            _check_equal(checks, key, route.get(key), expect[key])
    if "skip_pre_gate" in expect:
        _check_equal(checks, "skip_pre_gate", bool(route.get("skip_pre_gate")), bool(expect["skip_pre_gate"]))
    if "model_calls" in expect:
        actual = (route.get("cost_metrics") or {}).get("estimated_model_calls")
        _check_equal(checks, "model_calls", actual, expect["model_calls"])
    if expect.get("direct_answer_is_null") is True:
        _check_equal(checks, "direct_answer_is_null", route.get("direct_answer"), None)
    if expect.get("direct_answer_contains"):
        direct = route.get("direct_answer") or ""
        for term in expect["direct_answer_contains"]:
            _check_true(checks, f"direct_answer_contains:{term}", _contains(direct, term))
    if expect.get("coordinate_hit_ids"):
        actual_ids = [hit.get("id") for hit in route.get("coordinate_hits") or []]
        _check_true(checks, "coordinate_hit_ids", _subset(expect["coordinate_hit_ids"], actual_ids))

    return {"observed": _compact(route), "checks": checks}


def _run_kairos_case(case: Dict[str, Any], *, root: Path) -> Dict[str, Any]:
    from services.kairos_memory import answer_kairos_memory

    answer = answer_kairos_memory(case.get("input", ""), root)
    expect = case.get("expect") or {}
    checks: List[Dict[str, Any]] = []
    if expect.get("answer_is_null") is True:
        _check_equal(checks, "answer_is_null", answer, None)
    if expect.get("answer_not_null") is True:
        _check_true(checks, "answer_not_null", answer is not None)
    for term in expect.get("answer_contains") or []:
        _check_true(checks, f"answer_contains:{term}", _contains(answer or "", term))
    for term in expect.get("answer_not_contains") or []:
        _check_false(checks, f"answer_not_contains:{term}", _contains(answer or "", term))
    return {"observed": {"answer_preview": (answer or "")[:500], "answer_is_null": answer is None}, "checks": checks}


def _run_world_trigger_case(case: Dict[str, Any], *, root: Path) -> Dict[str, Any]:
    del root
    from services.world_simulator import should_trigger_world

    trigger = should_trigger_world(case.get("input", ""))
    expect = case.get("expect") or {}
    checks: List[Dict[str, Any]] = []
    for key in ("should_trigger", "explicit"):
        if key in expect:
            _check_equal(checks, key, trigger.get(key), expect[key])
    if expect.get("terms"):
        _check_true(checks, "terms", _subset(expect["terms"], trigger.get("terms") or []))
    return {"observed": trigger, "checks": checks}


def _run_world_simulation_case(case: Dict[str, Any], *, root: Path) -> Dict[str, Any]:
    from services.computer_tools import TOOL_REGISTRY
    from services.world_simulator import simulate_world

    result = simulate_world(
        input_text=case.get("input", ""),
        data_dir=root / "data",
        tool_names=TOOL_REGISTRY.keys(),
    )
    expect = case.get("expect") or {}
    checks: List[Dict[str, Any]] = []
    if "schema_version" in expect:
        _check_equal(checks, "schema_version", result.get("schema_version"), expect["schema_version"])
    if "needs_world_view" in expect:
        _check_equal(checks, "needs_world_view", _value_at(result, "evaluation.needs_world_view"), expect["needs_world_view"])
    if expect.get("recommended_scenario_in"):
        actual = _value_at(result, "evaluation.recommended_scenario")
        _check_true(checks, "recommended_scenario_in", actual in set(expect["recommended_scenario_in"]))
    if expect.get("entity_ids"):
        actual_ids = [entity.get("id") for entity in (result.get("world") or {}).get("entities") or []]
        _check_true(checks, "entity_ids", _subset(expect["entity_ids"], actual_ids))
    if expect.get("scenario_ids"):
        actual_ids = [scenario.get("id") for scenario in result.get("scenarios") or []]
        _check_true(checks, "scenario_ids", _subset(expect["scenario_ids"], actual_ids))
    return {"observed": _compact(result), "checks": checks}


def _run_runtime_identity_case(case: Dict[str, Any], *, root: Path) -> Dict[str, Any]:
    del root
    from services.runtime_identity import RUNTIME_IDENTITY_ID, with_runtime_identity

    prompt = with_runtime_identity(case.get("input", ""))
    expect = case.get("expect") or {}
    checks: List[Dict[str, Any]] = []
    if "identity_id" in expect:
        _check_equal(checks, "identity_id", RUNTIME_IDENTITY_ID, expect["identity_id"])
    for term in expect.get("contains") or []:
        _check_true(checks, f"contains:{term}", _contains(prompt, term))
    for term in expect.get("not_contains") or []:
        _check_false(checks, f"not_contains:{term}", _contains(prompt, term))
    return {"observed": {"identity_id": RUNTIME_IDENTITY_ID, "prompt_preview": prompt[:500]}, "checks": checks}


_CASE_RUNNERS = {
    "route": _run_route_case,
    "kairos_memory": _run_kairos_case,
    "world_trigger": _run_world_trigger_case,
    "world_simulation": _run_world_simulation_case,
    "runtime_identity": _run_runtime_identity_case,
}


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items() if k not in {"profile", "meta"}}
    if isinstance(value, list):
        return [_compact(v) for v in value[:12]]
    if isinstance(value, str) and len(value) > 800:
        return value[:800] + "...<truncated>"
    return value


def run_golden_cases(cases_path: Path = DEFAULT_CASES, *, root: Path = ROOT) -> Dict[str, Any]:
    payload = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    results: List[Dict[str, Any]] = []

    for case in payload.get("cases") or []:
        runner = _CASE_RUNNERS.get(case.get("type"))
        if runner is None:
            results.append({
                "id": case.get("id"),
                "type": case.get("type"),
                "passed": False,
                "checks": [{"name": "known_case_type", "passed": False, "actual": case.get("type")}],
            })
            continue
        try:
            detail = runner(case, root=root)
            checks = detail.get("checks") or []
            passed = all(check.get("passed") for check in checks)
            results.append({
                "id": case.get("id"),
                "type": case.get("type"),
                "input": case.get("input", ""),
                "passed": passed,
                "checks": checks,
                "observed": detail.get("observed"),
            })
        except Exception as exc:
            results.append({
                "id": case.get("id"),
                "type": case.get("type"),
                "input": case.get("input", ""),
                "passed": False,
                "checks": [{"name": "case_exception", "passed": False, "actual": f"{type(exc).__name__}: {exc}"}],
            })

    failed = [item for item in results if not item.get("passed")]
    return {
        "schema_version": payload.get("schema_version"),
        "suite_id": payload.get("suite_id"),
        "case_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "passed": not failed,
        "results": results,
    }
