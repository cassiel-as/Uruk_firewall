"""Strict validation for URUK controller-model JSONL datasets."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.controller_policy import (  # noqa: E402
    CONTROLLER_SCHEMA_VERSION,
    KNOWLEDGE_LAYERS,
    ROUTE_KINDS,
    TASK_PROFILES,
    TOOL_PERMISSIONS,
)


EXAMPLE_KEYS = {"schema_version", "example_id", "split", "source", "input", "output"}
SOURCE_KEYS = {"kind", "ref", "approved_for_training"}
INPUT_KEYS = {"user_input", "runtime_signals"}
SIGNAL_KEYS = {
    "schema_version",
    "text_length",
    "pipeline_mode",
    "selected_modes",
    "available_capabilities",
    "protocol_concept_detected",
    "coordinate_card_ids",
    "kairos_memory_match",
    "fresh_external_evidence_required",
    "forced_mode_requested",
    "estimated_context_tokens",
    "estimated_model_calls",
}
OUTPUT_KEYS = {
    "schema_version",
    "route_kind",
    "pipeline",
    "knowledge_layers",
    "task_profile",
    "model_budget",
    "tool_permission",
    "escalation_required",
    "confidence",
    "reason_codes",
}
SOURCE_KINDS = {
    "seed",
    "contrast_set",
    "coordinate_benchmark",
    "stability_golden",
    "approved_episode",
    "approved_shadow",
    "approved_factory",
}
SPLITS = {"train", "validation", "test"}
FORBIDDEN_KEYS = {
    "direct_answer",
    "assistant_answer",
    "voices",
    "council",
    "all_data_refs",
    "user_refs",
    "knowledge_trace",
    "kairos_content",
}
EXAMPLE_ID_RE = re.compile(r"^ctrl_[a-f0-9]{16}$")
REASON_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")


def _exact_keys(value: Any, expected: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        errors.append(f"{path}: missing keys {missing}")
    if extra:
        errors.append(f"{path}: unexpected keys {extra}")


def _list_of_strings(
    value: Any,
    path: str,
    errors: list[str],
    *,
    allowed: set[str] | frozenset[str] | None = None,
    max_items: int = 64,
    require_nonempty: bool = False,
) -> None:
    if not isinstance(value, list):
        errors.append(f"{path}: expected array")
        return
    if require_nonempty and not value:
        errors.append(f"{path}: must not be empty")
    if len(value) > max_items:
        errors.append(f"{path}: too many items")
    if len(value) != len(set(str(item) for item in value)):
        errors.append(f"{path}: duplicate items")
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item:
            errors.append(f"{path}[{idx}]: expected non-empty string")
        elif allowed is not None and item not in allowed:
            errors.append(f"{path}[{idx}]: unsupported value {item!r}")


def _find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_KEYS:
                hits.append(child_path)
            hits.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            hits.extend(_find_forbidden_keys(child, f"{path}[{idx}]"))
    return hits


def validate_controller_decision(value: Any, path: str = "$.output") -> list[str]:
    errors: list[str] = []
    _exact_keys(value, OUTPUT_KEYS, path, errors)
    if not isinstance(value, dict):
        return errors

    if value.get("schema_version") != CONTROLLER_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version: expected {CONTROLLER_SCHEMA_VERSION!r}")
    if value.get("route_kind") not in ROUTE_KINDS:
        errors.append(f"{path}.route_kind: unsupported value {value.get('route_kind')!r}")
    if not isinstance(value.get("pipeline"), str) or not value.get("pipeline"):
        errors.append(f"{path}.pipeline: expected non-empty string")
    _list_of_strings(value.get("knowledge_layers"), f"{path}.knowledge_layers", errors, allowed=KNOWLEDGE_LAYERS, max_items=8)
    if value.get("task_profile") not in TASK_PROFILES:
        errors.append(f"{path}.task_profile: unsupported value {value.get('task_profile')!r}")
    budget = value.get("model_budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or not 0 <= budget <= 12:
        errors.append(f"{path}.model_budget: expected integer in [0, 12]")
    if value.get("tool_permission") not in TOOL_PERMISSIONS:
        errors.append(f"{path}.tool_permission: unsupported value {value.get('tool_permission')!r}")
    if not isinstance(value.get("escalation_required"), bool):
        errors.append(f"{path}.escalation_required: expected boolean")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        errors.append(f"{path}.confidence: expected number in [0, 1]")
    _list_of_strings(value.get("reason_codes"), f"{path}.reason_codes", errors, max_items=16, require_nonempty=True)
    for idx, reason in enumerate(value.get("reason_codes") or []):
        if isinstance(reason, str) and not REASON_RE.fullmatch(reason):
            errors.append(f"{path}.reason_codes[{idx}]: invalid reason code")

    if value.get("route_kind") == "deterministic_memory" and value.get("model_budget") != 0:
        errors.append(f"{path}: deterministic memory must use zero model budget")
    if value.get("task_profile") == "local_language" and value.get("escalation_required") is True:
        errors.append(f"{path}: local language task cannot also require escalation")
    if value.get("tool_permission") in {"workspace_write_reviewed", "system_change_reviewed"} and not value.get("escalation_required"):
        errors.append(f"{path}: protected write permissions require escalation")
    return errors


def validate_example(value: Any) -> list[str]:
    errors: list[str] = []
    _exact_keys(value, EXAMPLE_KEYS, "$", errors)
    if not isinstance(value, dict):
        return errors

    if value.get("schema_version") != "uruk_controller_example.v1":
        errors.append("$.schema_version: expected 'uruk_controller_example.v1'")
    if not isinstance(value.get("example_id"), str) or not EXAMPLE_ID_RE.fullmatch(value.get("example_id") or ""):
        errors.append("$.example_id: invalid controller example id")
    if value.get("split") not in SPLITS:
        errors.append("$.split: unsupported split")

    source = value.get("source")
    _exact_keys(source, SOURCE_KEYS, "$.source", errors)
    if isinstance(source, dict):
        if source.get("kind") not in SOURCE_KINDS:
            errors.append("$.source.kind: unsupported source kind")
        if not isinstance(source.get("ref"), str) or not source.get("ref"):
            errors.append("$.source.ref: expected non-empty string")
        if source.get("approved_for_training") is not True:
            errors.append("$.source.approved_for_training: must be true")

    model_input = value.get("input")
    _exact_keys(model_input, INPUT_KEYS, "$.input", errors)
    if isinstance(model_input, dict):
        user_input = model_input.get("user_input")
        if not isinstance(user_input, str) or not 1 <= len(user_input) <= 4000:
            errors.append("$.input.user_input: expected 1..4000 characters")
        signals = model_input.get("runtime_signals")
        _exact_keys(signals, SIGNAL_KEYS, "$.input.runtime_signals", errors)
        if isinstance(signals, dict):
            if signals.get("schema_version") != "uruk_controller_signals.v1":
                errors.append("$.input.runtime_signals.schema_version: invalid version")
            if not isinstance(signals.get("text_length"), int) or signals.get("text_length") != len(user_input or ""):
                errors.append("$.input.runtime_signals.text_length: must match user input length")
            if not isinstance(signals.get("pipeline_mode"), str) or not signals.get("pipeline_mode"):
                errors.append("$.input.runtime_signals.pipeline_mode: expected non-empty string")
            _list_of_strings(signals.get("selected_modes"), "$.input.runtime_signals.selected_modes", errors, max_items=16)
            _list_of_strings(signals.get("available_capabilities"), "$.input.runtime_signals.available_capabilities", errors)
            _list_of_strings(signals.get("coordinate_card_ids"), "$.input.runtime_signals.coordinate_card_ids", errors, max_items=16)
            for key in (
                "protocol_concept_detected",
                "kairos_memory_match",
                "fresh_external_evidence_required",
                "forced_mode_requested",
            ):
                if not isinstance(signals.get(key), bool):
                    errors.append(f"$.input.runtime_signals.{key}: expected boolean")
            for key in ("estimated_context_tokens", "estimated_model_calls"):
                if not isinstance(signals.get(key), int) or isinstance(signals.get(key), bool) or signals.get(key) < 0:
                    errors.append(f"$.input.runtime_signals.{key}: expected non-negative integer")

    errors.extend(validate_controller_decision(value.get("output")))
    for hit in _find_forbidden_keys(value):
        errors.append(f"{hit}: forbidden training-data key")
    return errors


def iter_jsonl(path: Path) -> Iterable[tuple[int, Any]]:
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            yield line_number, json.loads(line)
        except json.JSONDecodeError as exc:
            yield line_number, {"_json_error": str(exc)}


def validate_dataset(paths: Iterable[Path]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    count = 0
    seen_ids: set[str] = set()
    seen_inputs: set[tuple[str, str, tuple[str, ...]]] = set()
    for path in paths:
        for line_number, example in iter_jsonl(path):
            count += 1
            if isinstance(example, dict) and "_json_error" in example:
                errors = [f"$: invalid JSON: {example['_json_error']}"]
            else:
                errors = validate_example(example)
                example_id = str((example or {}).get("example_id") or "")
                model_input = (example or {}).get("input") or {}
                signals = model_input.get("runtime_signals") or {}
                input_identity = (
                    " ".join(str(model_input.get("user_input") or "").casefold().split()),
                    str(signals.get("pipeline_mode") or "auto"),
                    tuple(str(item) for item in (signals.get("selected_modes") or [])),
                )
                if example_id in seen_ids:
                    errors.append("$.example_id: duplicate across dataset")
                if input_identity in seen_inputs:
                    errors.append("$.input: duplicate query and routing signals across dataset")
                seen_ids.add(example_id)
                seen_inputs.add(input_identity)
            if errors:
                issues.append({"path": str(path), "line": line_number, "errors": errors})
    return {
        "schema_version": "uruk_controller_dataset_validation.v1",
        "passed": not issues,
        "example_count": count,
        "issue_count": len(issues),
        "issues": issues,
    }


def dataset_paths(target: Path) -> list[Path]:
    target = Path(target)
    if target.is_dir():
        preferred = [target / name for name in ("train.jsonl", "validation.jsonl", "test.jsonl")]
        return [path for path in preferred if path.exists()]
    return [target]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate URUK controller-model JSONL data.")
    parser.add_argument("target", nargs="?", default=str(ROOT / "training" / "generated"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = validate_dataset(dataset_paths(Path(args.target)))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report["passed"] else "FAIL"
        print(f"URUK controller dataset {status}: {report['example_count']} examples, {report['issue_count']} issues")
        for issue in report["issues"][:10]:
            print(f"  {issue['path']}:{issue['line']} - {'; '.join(issue['errors'])}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
