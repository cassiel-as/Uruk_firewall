"""Apply the deterministic authority guard to raw controller predictions."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.controller_shadow import guard_controller_candidate  # noqa: E402
from training.benchmark_controller import run_benchmark  # noqa: E402
from training.dataset_validator import dataset_paths, iter_jsonl  # noqa: E402


def _examples(dataset: Path, *, split: str = "", example_ids: set[str] | None = None) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for path in dataset_paths(Path(dataset)):
        for _, value in iter_jsonl(path):
            if not isinstance(value, dict) or value.get("_json_error"):
                continue
            if split and value.get("split") != split:
                continue
            if example_ids and str(value.get("example_id") or "") not in example_ids:
                continue
            values.append(value)
    return values


def _predictions(path: Path) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for _, value in iter_jsonl(Path(path)):
        if not isinstance(value, dict):
            continue
        example_id = str(value.get("example_id") or "")
        output = value.get("output")
        if example_id and isinstance(output, dict):
            values[example_id] = value
    return values


def guard_predictions(
    *,
    dataset: Path,
    predictions: Path,
    output: Path,
    split: str = "",
    example_ids: set[str] | None = None,
) -> dict[str, Any]:
    examples = _examples(Path(dataset), split=split, example_ids=example_ids)
    raw = _predictions(Path(predictions))
    guarded_rows: list[dict[str, Any]] = []
    override_counts: Counter[str] = Counter()
    fallback_reasons: Counter[str] = Counter()
    route_accepted = 0
    raw_coverage = 0
    for example in examples:
        example_id = str(example.get("example_id") or "")
        raw_row = raw.get(example_id) or {}
        candidate = raw_row.get("output") if isinstance(raw_row.get("output"), dict) else {}
        raw_coverage += int(bool(candidate))
        guarded, guard = guard_controller_candidate(example.get("output") or {}, candidate)
        route_accepted += int(bool(guard["route_accepted"]))
        override_counts.update(str(item) for item in (guard.get("overridden_fields") or []))
        if guard.get("fallback_used"):
            fallback_reasons[str(guard.get("fallback_reason") or "unknown")] += 1
        guarded_rows.append({
            "example_id": example_id,
            "output": guarded,
            "candidate_meta": {
                **(raw_row.get("candidate_meta") or {}),
                "authority_guard": guard,
                "raw_output": candidate,
            },
        })

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        ("\n".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in guarded_rows) + "\n")
        if guarded_rows else "",
        encoding="utf-8",
    )
    ids = {str(example.get("example_id") or "") for example in examples}
    benchmark = run_benchmark(Path(dataset), predictions_path=output, split=split, example_ids=ids)
    count = len(examples)
    route_acceptance_rate = round(route_accepted / count, 6) if count else 0.0
    raw_prediction_coverage = round(raw_coverage / count, 6) if count else 0.0
    guard_gates = {
        "guarded_benchmark": bool(benchmark.get("passed")),
        "raw_prediction_coverage": raw_prediction_coverage == 1.0,
        "route_acceptance": route_acceptance_rate >= 0.98,
    }
    return {
        "schema_version": "uruk_guarded_controller_evaluation.v1",
        "passed": all(guard_gates.values()),
        "dataset": str(dataset),
        "raw_predictions": str(predictions),
        "guarded_predictions": str(output),
        "example_count": count,
        "raw_prediction_coverage": raw_prediction_coverage,
        "route_accepted_count": route_accepted,
        "route_acceptance_rate": route_acceptance_rate,
        "fallback_count": count - route_accepted,
        "fallback_reasons": dict(sorted(fallback_reasons.items())),
        "override_counts": dict(sorted(override_counts.items())),
        "guard_gates": guard_gates,
        "benchmark": benchmark,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate raw controller predictions behind the authority guard.")
    parser.add_argument("--dataset", default=str(ROOT / "training" / "generated"))
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", choices=("", "train", "validation", "test"), default="")
    parser.add_argument("--example-ids", default="")
    parser.add_argument("--write-report", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = guard_predictions(
        dataset=Path(args.dataset),
        predictions=Path(args.predictions),
        output=Path(args.output),
        split=args.split,
        example_ids={item.strip() for item in args.example_ids.split(",") if item.strip()} or None,
    )
    if args.write_report:
        path = Path(args.write_report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report["passed"] else "FAIL"
        print(
            f"Guarded controller evaluation {status}: {report['example_count']} examples, "
            f"route acceptance={report['route_acceptance_rate']}, fallbacks={report['fallback_count']}"
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
