"""Build privacy-gated JSONL data for the URUK Controller Model."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.controller_policy import (  # noqa: E402
    compile_controller_decision,
    compile_controller_example_input,
)
from training.contrast_cases import build_contrast_cases  # noqa: E402
from training.dataset_validator import validate_example  # noqa: E402


SEED_PATH = ROOT / "training" / "datasets" / "controller_seed_cases.json"
COORDINATE_CASES_PATH = ROOT / "data" / "benchmarks" / "benchmark_cases.json"
STABILITY_CASES_PATH = ROOT / "data" / "benchmarks" / "stability_golden_cases.json"
EPISODES_DIR = ROOT / "data" / "harness_episodes"
APPROVED_LEARNING_DIR = ROOT / "data" / "controller_learning" / "approved"
DEFAULT_OUTPUT_DIR = ROOT / "training" / "generated"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _source_ref(path: Path) -> str:
    try:
        return str(Path(path).relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(Path(path)).replace("\\", "/")


def _normalized_query(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _source_case(kind: str, ref: str, case: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "ref": ref,
        "query": str(case.get("input") or ""),
        "pipeline_mode": str(case.get("pipeline_mode") or "auto"),
        "selected_modes": list(case.get("selected_modes") or []),
        "expected_route_kind": case.get("expected_route_kind"),
        "expected_task_profile": case.get("expected_task_profile"),
        "split": case.get("split"),
        "split_group": str(case.get("family") or case.get("id") or ref),
    }


def collect_source_cases(*, include_approved_episodes: bool = True) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cases: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()

    for case in _load_json(SEED_PATH).get("cases") or []:
        cases.append(_source_case("seed", f"training/datasets/controller_seed_cases.json#{case.get('id')}", case))
        stats["seed_loaded"] += 1

    for case in build_contrast_cases():
        cases.append(_source_case("contrast_set", f"training/contrast_cases.py#{case.get('id')}", case))
        stats["contrast_set_loaded"] += 1

    for case in _load_json(COORDINATE_CASES_PATH).get("cases") or []:
        cases.append(_source_case("coordinate_benchmark", f"data/benchmarks/benchmark_cases.json#{case.get('id')}", case))
        stats["coordinate_benchmark_loaded"] += 1

    for case in _load_json(STABILITY_CASES_PATH).get("cases") or []:
        if case.get("type") != "route":
            continue
        expected = case.get("expect") or {}
        enriched = {
            **case,
            "expected_route_kind": expected.get("route_kind"),
        }
        cases.append(_source_case("stability_golden", f"data/benchmarks/stability_golden_cases.json#{case.get('id')}", enriched))
        stats["stability_golden_loaded"] += 1

    if include_approved_episodes and EPISODES_DIR.exists():
        for path in sorted(EPISODES_DIR.rglob("*.json")):
            stats["episodes_scanned"] += 1
            episode = _load_json(path)
            run = episode.get("run") or {}
            approved = episode.get("training_approved") is True or run.get("training_approved") is True
            if not approved:
                stats["episodes_skipped_not_approved"] += 1
                continue
            query = run.get("input")
            if not isinstance(query, str) or not query.strip():
                stats["episodes_skipped_no_input"] += 1
                continue
            cases.append({
                "kind": "approved_episode",
                "ref": _source_ref(path),
                "query": query,
                "pipeline_mode": str(run.get("pipeline_mode") or "auto"),
                "selected_modes": list(run.get("selected_modes") or []),
                "expected_route_kind": ((run.get("cost_metrics") or {}).get("route_kind") or None),
                "expected_task_profile": None,
                "split": None,
                "split_group": _source_ref(path),
            })
            stats["approved_episodes_loaded"] += 1

    if APPROVED_LEARNING_DIR.exists():
        for path in sorted(APPROVED_LEARNING_DIR.glob("learn_*.json")):
            stats["learning_candidates_scanned"] += 1
            record = _load_json(path)
            if record.get("status") != "approved":
                stats["learning_candidates_skipped_not_approved"] += 1
                continue
            model_input = record.get("input") or {}
            signals = model_input.get("runtime_signals") or {}
            query = model_input.get("user_input")
            reference = record.get("reference") or {}
            review = record.get("review") or {}
            provenance = record.get("provenance") or {}
            if not isinstance(query, str) or not query.strip():
                stats["learning_candidates_skipped_no_input"] += 1
                continue
            cases.append({
                "kind": "approved_factory" if provenance.get("type") == "data_factory" else "approved_shadow",
                "ref": _source_ref(path),
                "query": query,
                "pipeline_mode": str(signals.get("pipeline_mode") or "auto"),
                "selected_modes": list(signals.get("selected_modes") or []),
                "expected_route_kind": reference.get("route_kind"),
                "expected_task_profile": reference.get("task_profile"),
                "split": str(review.get("training_split") or "train"),
                "split_group": str(record.get("candidate_id") or path.stem),
            })
            stats["approved_learning_candidates_loaded"] += 1

    return cases, dict(stats)


def _split_for(split_group: str) -> str:
    bucket = int(hashlib.sha256(split_group.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"


def _example_id(query: str, pipeline_mode: str, selected_modes: Iterable[str]) -> str:
    material = json.dumps(
        {
            "query": _normalized_query(query),
            "pipeline_mode": pipeline_mode,
            "selected_modes": list(selected_modes),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "ctrl_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_examples(*, include_approved_episodes: bool = True, strict_expectations: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_cases, source_stats = collect_source_cases(include_approved_episodes=include_approved_episodes)
    examples: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()

    for case in source_cases:
        query = str(case.get("query") or "").strip()
        pipeline_mode = str(case.get("pipeline_mode") or "auto")
        selected_modes = tuple(str(item) for item in (case.get("selected_modes") or []))
        dedupe_key = (_normalized_query(query), pipeline_mode, selected_modes)
        if not query or dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        decision = compile_controller_decision(
            query,
            root=ROOT,
            pipeline_mode=pipeline_mode,
            selected_modes=selected_modes,
        )
        expected_route = case.get("expected_route_kind")
        expected_profile = case.get("expected_task_profile")
        if expected_route and decision["route_kind"] != expected_route:
            issues.append(f"{case['ref']}: expected route {expected_route}, got {decision['route_kind']}")
        if expected_profile and decision["task_profile"] != expected_profile:
            issues.append(f"{case['ref']}: expected profile {expected_profile}, got {decision['task_profile']}")

        example_id = _example_id(query, pipeline_mode, selected_modes)
        split = str(case.get("split") or _split_for(str(case.get("split_group") or example_id)))
        example = {
            "schema_version": "uruk_controller_example.v1",
            "example_id": example_id,
            "split": split,
            "source": {
                "kind": case["kind"],
                "ref": case["ref"],
                "approved_for_training": True,
            },
            "input": compile_controller_example_input(
                query,
                root=ROOT,
                pipeline_mode=pipeline_mode,
                selected_modes=selected_modes,
            ),
            "output": decision,
        }
        validation_errors = validate_example(example)
        if validation_errors:
            issues.append(f"{case['ref']}: {'; '.join(validation_errors)}")
        examples.append(example)

    if strict_expectations and issues:
        raise ValueError("Controller dataset build failed:\n" + "\n".join(issues[:30]))

    return examples, {
        "source_stats": source_stats,
        "build_issues": issues,
        "deduplicated_source_count": len(seen),
    }


def write_dataset(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    include_approved_episodes: bool = True,
    strict_expectations: bool = True,
) -> dict[str, Any]:
    examples, build_meta = build_examples(
        include_approved_episodes=include_approved_episodes,
        strict_expectations=strict_expectations,
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    split_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for example in examples:
        split_counts[example["split"]] += 1
        route_counts[example["output"]["route_kind"]] += 1
        source_counts[example["source"]["kind"]] += 1

    for split in ("train", "validation", "test"):
        lines = [
            json.dumps(example, ensure_ascii=False, separators=(",", ":"))
            for example in examples
            if example["split"] == split
        ]
        (output_dir / f"{split}.jsonl").write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")

    all_lines = [json.dumps(example, ensure_ascii=False, separators=(",", ":")) for example in examples]
    (output_dir / "all.jsonl").write_text(("\n".join(all_lines) + "\n") if all_lines else "", encoding="utf-8")

    manifest = {
        "schema_version": "uruk_controller_dataset_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "example_count": len(examples),
        "split_counts": dict(sorted(split_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "privacy_policy": {
            "raw_harness_episodes_included_only_when_training_approved": True,
            "shadow_cases_included_only_after_review_approval": True,
            "shadow_inputs_are_sanitized_before_queueing": True,
            "answers_and_kairos_content_excluded": True,
        },
        **build_meta,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build URUK controller-model training data.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--skip-approved-episodes", action="store_true")
    parser.add_argument("--allow-expectation-mismatches", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    manifest = write_dataset(
        Path(args.output_dir),
        include_approved_episodes=not args.skip_approved_episodes,
        strict_expectations=not args.allow_expectation_mismatches,
    )
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"URUK controller dataset built: {manifest['example_count']} examples")
        print(f"  splits: {manifest['split_counts']}")
        print(f"  routes: {manifest['route_counts']}")
        print(f"  episodes skipped without approval: {manifest['source_stats'].get('episodes_skipped_not_approved', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
