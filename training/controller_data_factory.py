"""Generate review-gated controller candidates from train-only source cases.

Phase one intentionally uses deterministic, meaning-preserving rewrites. It
does not call an LLM and never derives candidates from validation or test.
"""
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

from services.controller_learning import accumulate_learning_candidate  # noqa: E402
from services.controller_policy import compile_controller_decision, compile_controller_example_input  # noqa: E402
from training.dataset_validator import iter_jsonl, validate_controller_decision  # noqa: E402


DEFAULT_DATASET = ROOT / "training" / "generated" / "train.jsonl"
FACTORY_VERSION = "deterministic_rewrite.v1"
ROUTE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "small_task": (
        "Please answer this briefly and directly: {query}",
        "Quick question: {query}",
        "Give a concise response to this request: {query}",
    ),
    "deep_reasoning": (
        "Please analyse this carefully: {query}",
        "Give a reasoned explanation for this: {query}",
        "I want to understand this more deeply: {query}",
    ),
    "code_task": (
        "Please handle this coding task: {query}",
        "Work on this implementation request: {query}",
        "Please inspect and resolve this code request: {query}",
    ),
    "tool_task": (
        "Please use the available tools to do this: {query}",
        "Carry out this tool operation: {query}",
        "Please perform this action using the system tools: {query}",
    ),
    "world_query": (
        "Please verify this using reliable public sources: {query}",
        "Check current external sources for this: {query}",
        "I need externally verified information about this: {query}",
    ),
    "self_upgrade": (
        "Please perform this system maintenance request: {query}",
        "Handle this self-upgrade operation carefully: {query}",
        "Run this upgrade-related request: {query}",
    ),
    "deterministic_memory": (
        "Please answer from Kairos memory only: {query}",
        "Look up this Kairos memory request: {query}",
        "Use the reviewed Kairos memory index for this: {query}",
    ),
    "forced": (
        "Please process this request carefully: {query}",
        "Handle the following request: {query}",
        "Please respond to this request: {query}",
    ),
}


def _load_train_examples(dataset: Path) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for _, value in iter_jsonl(Path(dataset)):
        if not isinstance(value, dict) or value.get("_json_error"):
            continue
        if value.get("split") != "train":
            continue
        if (value.get("source") or {}).get("kind") in {"approved_shadow", "approved_factory"}:
            continue
        examples.append(value)
    return examples


def generate_variants(example: dict[str, Any], *, max_per_source: int = 3) -> list[dict[str, str]]:
    query = str((example.get("input") or {}).get("user_input") or "").strip()
    route = str((example.get("output") or {}).get("route_kind") or "")
    templates = ROUTE_TEMPLATES.get(route, ())
    variants: list[dict[str, str]] = []
    seen = {" ".join(query.casefold().split())}
    for index, template in enumerate(templates[:max(0, max_per_source)], start=1):
        variant = template.format(query=query).strip()
        normalized = " ".join(variant.casefold().split())
        if variant and normalized not in seen:
            variants.append({"mutation": f"{route}.rewrite_{index}", "query": variant})
            seen.add(normalized)
    return variants


def _exact_comparison(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_valid": True,
        "schema_errors": [],
        "route_match": True,
        "authority_match": True,
        "escalation_match": True,
        "exact_match": True,
        "differences": {},
    }


def run_factory(
    *,
    dataset: Path = DEFAULT_DATASET,
    policy_root: Path = ROOT,
    queue_root: Path = ROOT,
    max_per_source: int = 3,
    limit: int = 0,
    write: bool = False,
) -> dict[str, Any]:
    examples = _load_train_examples(dataset)
    existing_inputs = {
        " ".join(str((example.get("input") or {}).get("user_input") or "").casefold().split())
        for example in examples
    }
    stats: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    config = {
        "learning_queue_enabled": True,
        "agreement_sample_rate": 1.0,
        "max_records_per_day": max(500, limit or 0, len(examples) * max(1, max_per_source)),
    }

    for example in examples:
        source_output = example.get("output") or {}
        source_input = example.get("input") or {}
        signals = source_input.get("runtime_signals") or {}
        for variant in generate_variants(example, max_per_source=max_per_source):
            if limit and stats["considered"] >= limit:
                break
            stats["considered"] += 1
            query = variant["query"]
            normalized = " ".join(query.casefold().split())
            if normalized in existing_inputs:
                stats["skipped_existing_input"] += 1
                continue
            decision = compile_controller_decision(
                query,
                root=Path(policy_root),
                pipeline_mode=str(signals.get("pipeline_mode") or "auto"),
                selected_modes=list(signals.get("selected_modes") or []),
            )
            if (
                decision.get("route_kind") != source_output.get("route_kind")
                or decision.get("task_profile") != source_output.get("task_profile")
            ):
                stats["skipped_teacher_changed_label"] += 1
                if len(samples) < 20:
                    samples.append({
                        "status": "teacher_changed_label",
                        "source": source_input.get("user_input"),
                        "variant": query,
                        "expected_route": source_output.get("route_kind"),
                        "actual_route": decision.get("route_kind"),
                    })
                continue
            stats["label_preserved"] += 1
            route_counts[str(decision.get("route_kind") or "unknown")] += 1
            if not write:
                stats["dry_run_candidates"] += 1
                continue
            model_input = compile_controller_example_input(
                query,
                root=Path(policy_root),
                pipeline_mode=str(signals.get("pipeline_mode") or "auto"),
                selected_modes=list(signals.get("selected_modes") or []),
            )
            result = accumulate_learning_candidate(
                query,
                root=Path(queue_root),
                model_input=model_input,
                reference=decision,
                candidate=decision,
                comparison=_exact_comparison(decision),
                config=config,
                provenance={
                    "type": "data_factory",
                    "factory_version": FACTORY_VERSION,
                    "source_split": "train",
                    "source_example_id": example.get("example_id"),
                    "source_ref": (example.get("source") or {}).get("ref"),
                    "mutation": variant["mutation"],
                },
                force_collect=True,
                priority_override="low",
                collection_reasons_override=["factory_generated", "teacher_label_preserved"],
                increment_duplicate_count=False,
            )
            stats[str(result.get("status") or "unknown")] += 1
        if limit and stats["considered"] >= limit:
            break

    return {
        "schema_version": "uruk_controller_data_factory_report.v1",
        "factory_version": FACTORY_VERSION,
        "write": write,
        "source_split": "train",
        "source_example_count": len(examples),
        "max_per_source": max_per_source,
        "limit": limit,
        "stats": dict(sorted(stats.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "teacher_changed_label_samples": samples,
    }


def audit_factory_queue(*, queue_root: Path = ROOT, policy_root: Path = ROOT) -> dict[str, Any]:
    pending_dir = Path(queue_root) / "data" / "controller_learning" / "pending"
    issues: list[dict[str, Any]] = []
    route_counts: Counter[str] = Counter()
    checked = 0
    if not pending_dir.exists():
        return {
            "schema_version": "uruk_controller_data_factory_audit.v1",
            "passed": True,
            "checked": 0,
            "route_counts": {},
            "issue_count": 0,
            "issues": [],
        }
    for path in sorted(pending_dir.glob("learn_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        provenance = record.get("provenance") or {}
        if provenance.get("type") != "data_factory":
            continue
        checked += 1
        errors: list[str] = []
        if record.get("status") != "pending":
            errors.append("factory candidate is not pending")
        if provenance.get("source_split") != "train":
            errors.append("factory candidate source split is not train")
        reference = record.get("reference") or {}
        errors.extend(validate_controller_decision(reference))
        model_input = record.get("input") or {}
        query = str(model_input.get("user_input") or "")
        signals = model_input.get("runtime_signals") or {}
        if not query:
            errors.append("candidate input is empty")
        current = compile_controller_decision(
            query,
            root=Path(policy_root),
            pipeline_mode=str(signals.get("pipeline_mode") or "auto"),
            selected_modes=list(signals.get("selected_modes") or []),
        )
        for key in ("route_kind", "task_profile", "tool_permission", "escalation_required", "pipeline"):
            if current.get(key) != reference.get(key):
                errors.append(f"current teacher changed {key}: {reference.get(key)!r} -> {current.get(key)!r}")
        route_counts[str(reference.get("route_kind") or "unknown")] += 1
        if errors:
            issues.append({"candidate_id": record.get("candidate_id"), "path": str(path), "errors": errors})
    return {
        "schema_version": "uruk_controller_data_factory_audit.v1",
        "passed": not issues,
        "checked": checked,
        "route_counts": dict(sorted(route_counts.items())),
        "issue_count": len(issues),
        "issues": issues[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate train-only controller learning candidates.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--max-per-source", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--audit-queue", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-report", default="")
    args = parser.parse_args()
    report = (
        audit_factory_queue()
        if args.audit_queue
        else run_factory(
            dataset=Path(args.dataset),
            max_per_source=max(0, args.max_per_source),
            limit=max(0, args.limit),
            write=args.write,
        )
    )
    if args.write_report:
        path = Path(args.write_report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if args.audit_queue:
            status = "PASS" if report["passed"] else "FAIL"
            print(f"Controller Data Factory audit {status}: {report['checked']} checked, {report['issue_count']} issues")
            print(f"  routes: {report['route_counts']}")
        else:
            mode = "WRITE" if args.write else "DRY RUN"
            print(f"Controller Data Factory {mode}: {report['stats']}")
            print(f"  routes: {report['route_counts']}")
    return 0 if not args.audit_queue or report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
