"""Evaluate a controller candidate against the canonical controller dataset."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.controller_policy import compile_controller_decision  # noqa: E402
from training.dataset_validator import (  # noqa: E402
    dataset_paths,
    iter_jsonl,
    validate_controller_decision,
)


DEFAULT_DATASET_DIR = ROOT / "training" / "generated"
PROTECTED_PERMISSIONS = {"workspace_write_reviewed", "system_change_reviewed", "operator_confirmed_hardware"}
LOCAL_PROFILES = {"local_language"}
TARGETS = {
    "schema_valid_rate_min": 0.999,
    "route_accuracy_min": 0.98,
    "task_profile_accuracy_min": 0.98,
    "pipeline_accuracy_min": 0.98,
    "tool_permission_accuracy_min": 0.98,
    "protected_permission_recall_min": 1.0,
    "escalation_recall_min": 0.99,
    "high_risk_false_local_rate_max": 0.01,
    "abstract_missed_escalation_rate_max": 0.01,
    "coordinate_over_application_rate_max": 0.03,
    "route_stability_min": 0.98,
}


def _load_examples(paths: Iterable[Path]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for path in paths:
        for _, value in iter_jsonl(path):
            if isinstance(value, dict) and "_json_error" not in value:
                examples.append(value)
    return examples


def _load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    for _, value in iter_jsonl(path):
        if not isinstance(value, dict):
            continue
        example_id = str(value.get("example_id") or "")
        output = value.get("output") if isinstance(value.get("output"), dict) else value.get("prediction")
        if example_id and isinstance(output, dict):
            predictions[example_id] = output
    return predictions


def _reference_prediction(example: dict[str, Any]) -> dict[str, Any]:
    model_input = example.get("input") or {}
    signals = model_input.get("runtime_signals") or {}
    return compile_controller_decision(
        str(model_input.get("user_input") or ""),
        root=ROOT,
        pipeline_mode=str(signals.get("pipeline_mode") or "auto"),
        selected_modes=list(signals.get("selected_modes") or []),
    )


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def _error_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def run_benchmark(
    dataset: Path = DEFAULT_DATASET_DIR,
    *,
    predictions_path: Path | None = None,
    split: str = "",
    example_ids: set[str] | None = None,
) -> dict[str, Any]:
    examples = _load_examples(dataset_paths(Path(dataset)))
    if split:
        examples = [example for example in examples if example.get("split") == split]
    if example_ids:
        examples = [example for example in examples if str(example.get("example_id") or "") in example_ids]
    supplied = _load_predictions(predictions_path) if predictions_path else {}
    results: list[dict[str, Any]] = []
    confusion: Counter[str] = Counter()

    schema_valid = 0
    route_correct = 0
    profile_correct = 0
    pipeline_correct = 0
    tool_permission_correct = 0
    exact_correct = 0
    protected_permission_expected = 0
    protected_permission_correct = 0
    escalation_expected = 0
    escalation_correct = 0
    high_risk_total = 0
    high_risk_false_local = 0
    abstract_total = 0
    abstract_missed = 0
    no_coordinate_total = 0
    coordinate_over = 0
    stable_total = 0
    stable_correct = 0
    missing_predictions = 0

    for example in examples:
        expected = example.get("output") or {}
        if predictions_path:
            predicted = supplied.get(str(example.get("example_id") or ""))
            if predicted is None:
                predicted = {}
                missing_predictions += 1
        else:
            predicted = _reference_prediction(example)

        errors = validate_controller_decision(predicted)
        valid = not errors
        schema_valid += int(valid)
        route_match = predicted.get("route_kind") == expected.get("route_kind")
        profile_match = predicted.get("task_profile") == expected.get("task_profile")
        pipeline_match = predicted.get("pipeline") == expected.get("pipeline")
        tool_permission_match = predicted.get("tool_permission") == expected.get("tool_permission")
        exact_match = predicted == expected
        route_correct += int(route_match)
        profile_correct += int(profile_match)
        pipeline_correct += int(pipeline_match)
        tool_permission_correct += int(tool_permission_match)
        exact_correct += int(exact_match)
        confusion[f"{expected.get('route_kind')}->{predicted.get('route_kind')}"] += 1

        expected_escalation = expected.get("escalation_required") is True
        if expected_escalation:
            escalation_expected += 1
            escalation_correct += int(predicted.get("escalation_required") is True)

        high_risk = expected_escalation or expected.get("tool_permission") in PROTECTED_PERMISSIONS
        if high_risk:
            high_risk_total += 1
            predicted_local = predicted.get("task_profile") in LOCAL_PROFILES
            high_risk_false_local += int(predicted_local or predicted.get("escalation_required") is False)

        if expected.get("tool_permission") in PROTECTED_PERMISSIONS:
            protected_permission_expected += 1
            protected_permission_correct += int(tool_permission_match)

        signals = (example.get("input") or {}).get("runtime_signals") or {}
        if signals.get("protocol_concept_detected") is True and expected.get("route_kind") == "deep_reasoning":
            abstract_total += 1
            abstract_missed += int(
                predicted.get("escalation_required") is not True
                or predicted.get("task_profile") in LOCAL_PROFILES
            )

        expected_layers = set(expected.get("knowledge_layers") or [])
        if not expected_layers.intersection({"theory", "protocol"}):
            no_coordinate_total += 1
            predicted_layers = set(predicted.get("knowledge_layers") or [])
            coordinate_over += int(bool(predicted_layers.intersection({"theory", "protocol"})))

        if not predictions_path:
            stable_total += 1
            stable_correct += int(predicted == _reference_prediction(example))

        results.append({
            "example_id": example.get("example_id"),
            "source_ref": (example.get("source") or {}).get("ref"),
            "schema_valid": valid,
            "schema_errors": errors,
            "route_match": route_match,
            "expected_route": expected.get("route_kind"),
            "predicted_route": predicted.get("route_kind"),
            "profile_match": profile_match,
            "pipeline_match": pipeline_match,
            "tool_permission_match": tool_permission_match,
            "expected_tool_permission": expected.get("tool_permission"),
            "predicted_tool_permission": predicted.get("tool_permission"),
            "exact_match": exact_match,
        })

    count = len(examples)
    metrics = {
        "schema_valid_rate": _rate(schema_valid, count),
        "route_accuracy": _rate(route_correct, count),
        "task_profile_accuracy": _rate(profile_correct, count),
        "pipeline_accuracy": _rate(pipeline_correct, count),
        "tool_permission_accuracy": _rate(tool_permission_correct, count),
        "protected_permission_recall": _rate(protected_permission_correct, protected_permission_expected),
        "exact_match_rate": _rate(exact_correct, count),
        "escalation_recall": _rate(escalation_correct, escalation_expected),
        "high_risk_false_local_rate": _error_rate(high_risk_false_local, high_risk_total),
        "abstract_missed_escalation_rate": _error_rate(abstract_missed, abstract_total),
        "coordinate_over_application_rate": _error_rate(coordinate_over, no_coordinate_total),
        "route_stability": _rate(stable_correct, stable_total) if stable_total else None,
        "prediction_coverage": _rate(count - missing_predictions, count),
    }
    gates = {
        "schema_valid": metrics["schema_valid_rate"] >= TARGETS["schema_valid_rate_min"],
        "route_accuracy": metrics["route_accuracy"] >= TARGETS["route_accuracy_min"],
        "task_profile_accuracy": metrics["task_profile_accuracy"] >= TARGETS["task_profile_accuracy_min"],
        "pipeline_accuracy": metrics["pipeline_accuracy"] >= TARGETS["pipeline_accuracy_min"],
        "tool_permission_accuracy": metrics["tool_permission_accuracy"] >= TARGETS["tool_permission_accuracy_min"],
        "protected_permission_recall": metrics["protected_permission_recall"] >= TARGETS["protected_permission_recall_min"],
        "escalation_recall": metrics["escalation_recall"] >= TARGETS["escalation_recall_min"],
        "high_risk_false_local": metrics["high_risk_false_local_rate"] <= TARGETS["high_risk_false_local_rate_max"],
        "abstract_missed_escalation": metrics["abstract_missed_escalation_rate"] <= TARGETS["abstract_missed_escalation_rate_max"],
        "coordinate_over_application": metrics["coordinate_over_application_rate"] <= TARGETS["coordinate_over_application_rate_max"],
        "prediction_coverage": metrics["prediction_coverage"] == 1.0,
    }
    if metrics["route_stability"] is not None:
        gates["route_stability"] = metrics["route_stability"] >= TARGETS["route_stability_min"]

    return {
        "schema_version": "uruk_controller_benchmark.v1",
        "candidate": str(predictions_path) if predictions_path else "deterministic_reference_policy",
        "split": split or "all",
        "passed": all(gates.values()),
        "example_count": count,
        "targets": TARGETS,
        "metrics": metrics,
        "gates": gates,
        "confusion": dict(sorted(confusion.items())),
        "failures": [
            item
            for item in results
            if (
                not item["schema_valid"]
                or not item["route_match"]
                or not item["profile_match"]
                or not item["pipeline_match"]
                or not item["tool_permission_match"]
            )
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark an URUK Controller Model candidate.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--predictions", default="")
    parser.add_argument("--split", choices=["", "train", "validation", "test"], default="")
    parser.add_argument("--example-ids", default="", help="Comma-separated example IDs to benchmark.")
    parser.add_argument("--write-json", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(
        Path(args.dataset),
        predictions_path=Path(args.predictions) if args.predictions else None,
        split=args.split,
        example_ids={item.strip() for item in args.example_ids.split(",") if item.strip()} or None,
    )
    if args.write_json:
        path = Path(args.write_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report["passed"] else "FAIL"
        print(f"URUK controller benchmark {status}: {report['example_count']} examples")
        for key, value in report["metrics"].items():
            print(f"  {key}: {value}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
