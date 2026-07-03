"""Generate review-gated minimal pairs for controller routing boundaries.

Hard negatives are deliberately similar inputs that require different routes,
profiles, or pipelines. Every member is checked against the current
deterministic teacher before a complete pair can enter the pending queue.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.controller_learning import STATUSES, accumulate_learning_candidate  # noqa: E402
from services.controller_policy import compile_controller_decision, compile_controller_example_input  # noqa: E402
from training.dataset_validator import iter_jsonl, validate_controller_decision  # noqa: E402


DEFAULT_DATASET = ROOT / "training" / "generated" / "all.jsonl"
FACTORY_VERSION = "hard_negative.v1"
CRITICAL_FIELDS = (
    "route_kind",
    "task_profile",
    "tool_permission",
    "escalation_required",
    "pipeline",
)


def _pair(
    pair_id: str,
    *members: tuple[str, str, str, str, str],
) -> dict[str, Any]:
    return {
        "pair_id": pair_id,
        "members": [
            {
                "member_id": member_id,
                "query": query,
                "pipeline_mode": pipeline_mode,
                "expected_route": route,
                "expected_profile": profile,
            }
            for member_id, query, pipeline_mode, route, profile in members
        ],
    }


def build_hard_negative_pairs() -> list[dict[str, Any]]:
    """Return curated minimal pairs kept outside held-out evaluation splits."""
    return [
        _pair(
            "abstract-vs-quoted-translation",
            ("abstract", "Explain what freedom means as an abstract concept.", "auto", "deep_reasoning", "deep_reasoning"),
            ("translation", "Translate the sentence 'Explain what freedom means as an abstract concept.' into French.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "identity-vs-quoted-formatting",
            ("abstract", "Define identity as an abstract concept in plain language.", "auto", "deep_reasoning", "deep_reasoning"),
            ("formatting", "Rewrite the phrase 'Define identity as an abstract concept' in lowercase.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "browser-action-vs-translation",
            ("action", "Open browser and inspect the visible page now.", "auto", "tool_task", "auto"),
            ("translation", "Translate the sentence 'Open browser and inspect the visible page now.' into German.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "file-action-vs-translation",
            ("action", "Open the local file and read its contents now.", "auto", "tool_task", "auto"),
            ("translation", "Translate the sentence 'Open the local file and read its contents now.' into Spanish.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "code-action-vs-translation",
            ("action", "Fix this Python bug and add a regression test now.", "auto", "code_task", "code_coworker"),
            ("translation", "Translate the sentence 'Fix this Python bug and add a regression test now.' into French.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "code-rewrite-vs-text-rewrite",
            ("code", "Rewrite this Python function to handle timeout errors.", "auto", "code_task", "code_coworker"),
            ("formatting", "Rewrite the phrase 'Python function timeout error' in lowercase.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "upgrade-action-vs-translation",
            ("action", "Run the self-upgrade benchmark harness report now.", "auto", "self_upgrade", "upgrade"),
            ("translation", "Translate the sentence 'Run the self-upgrade benchmark harness report now.' into Italian.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "upgrade-report-vs-formatting",
            ("action", "Generate the prompt regression report before self upgrade.", "auto", "self_upgrade", "upgrade"),
            ("formatting", "Rewrite the phrase 'prompt regression report' in title case.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "world-query-vs-translation",
            ("world", "What happened in world history on 2025-12-25 according to public sources?", "auto", "world_query", "api_reasoning"),
            ("translation", "Translate the sentence 'What happened in world history on 2025-12-25?' into Japanese.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "same-date-world-vs-kairos",
            ("world", "What happened in world history on 2026-03-08?", "auto", "world_query", "api_reasoning"),
            ("kairos", "What can Kairos recall about the date 2026-03-08?", "auto", "deterministic_memory", "deterministic"),
        ),
        _pair(
            "same-date-find-world-vs-kairos",
            ("world", "Find world events for 2026-03-08.", "auto", "world_query", "api_reasoning"),
            ("kairos", "Retrieve Kairos memory associated with 2026-03-08.", "auto", "deterministic_memory", "deterministic"),
        ),
        _pair(
            "same-input-auto-vs-forced-news",
            ("auto", "Check this simple topic.", "auto", "small_task", "local_language"),
            ("forced", "Check this simple topic.", "news", "forced", "auto"),
        ),
        _pair(
            "same-input-auto-vs-tool-workshop",
            ("auto", "Design a bounded tool for text cleanup.", "auto", "tool_task", "auto"),
            ("forced", "Design a bounded tool for text cleanup.", "tool_workshop", "forced", "auto"),
        ),
        _pair(
            "arithmetic-vs-arithmetic-philosophy",
            ("calculation", "Calculate 17 plus 25.", "auto", "small_task", "local_language"),
            ("philosophy", "Analyse whether arithmetic truth depends on formal systems.", "auto", "deep_reasoning", "deep_reasoning"),
        ),
        _pair(
            "factual-definition-vs-abstract-definition",
            ("fact", "Name the capital city of Canada in one word.", "auto", "small_task", "local_language"),
            ("abstract", "Define justice as an abstract concept in one paragraph.", "auto", "deep_reasoning", "deep_reasoning"),
        ),
        _pair(
            "copilot-action-vs-translation",
            ("action", "Use Windows Copilot to inspect the taskbar now.", "auto", "tool_task", "windows_copilot"),
            ("translation", "Translate the sentence 'Use Windows Copilot to inspect the taskbar now.' into French.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "screenshot-action-vs-translation",
            ("action", "Capture a screenshot and inspect the visible error now.", "auto", "tool_task", "auto"),
            ("translation", "Translate the sentence 'Capture a screenshot and inspect the visible error now.' into German.", "auto", "small_task", "local_language"),
        ),
        _pair(
            "history-concept-vs-world-history",
            ("concept", "Explain why history shapes identity.", "auto", "deep_reasoning", "deep_reasoning"),
            ("world", "Find public world-history events dated 2024-11-11.", "auto", "world_query", "api_reasoning"),
        ),
        _pair(
            "kairos-concept-vs-kairos-memory",
            ("concept", "Explain Kairos as a concept.", "auto", "deep_reasoning", "deep_reasoning"),
            ("memory", "Look up what Kairos records for the date 2026-03-08.", "auto", "deterministic_memory", "deterministic"),
        ),
        _pair(
            "self-improvement-analysis-vs-action",
            ("analysis", "Evaluate whether autonomous self-improvement is safe.", "auto", "deep_reasoning", "deep_reasoning"),
            ("action", "Run the self-upgrade stability check.", "auto", "self_upgrade", "upgrade"),
        ),
        _pair(
            "agent-router-implementation-vs-analysis",
            ("implementation", "Implement a reliable agent router in Python.", "auto", "code_task", "code_coworker"),
            ("analysis", "Compare architecture strategies for a reliable agent router.", "auto", "deep_reasoning", "deep_reasoning"),
        ),
        _pair(
            "process-tool-vs-process-risk-analysis",
            ("action", "Use the tool to inspect the currently running process.", "auto", "tool_task", "auto"),
            ("analysis", "Analyse the risks of allowing tools to inspect running processes.", "auto", "deep_reasoning", "deep_reasoning"),
        ),
    ]


def _input_key(query: str, pipeline_mode: str, selected_modes: list[str] | None = None) -> str:
    material = {
        "query": " ".join(str(query or "").casefold().split()),
        "pipeline_mode": str(pipeline_mode or "auto"),
        "selected_modes": sorted(str(item) for item in (selected_modes or [])),
    }
    return json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _existing_input_keys(dataset: Path) -> set[str]:
    keys: set[str] = set()
    if not Path(dataset).exists():
        return keys
    for _, value in iter_jsonl(Path(dataset)):
        if not isinstance(value, dict) or value.get("_json_error"):
            continue
        model_input = value.get("input") or {}
        signals = model_input.get("runtime_signals") or {}
        keys.add(_input_key(
            str(model_input.get("user_input") or ""),
            str(signals.get("pipeline_mode") or "auto"),
            list(signals.get("selected_modes") or []),
        ))
    return keys


def _exact_comparison() -> dict[str, Any]:
    return {
        "schema_valid": True,
        "schema_errors": [],
        "route_match": True,
        "authority_match": True,
        "escalation_match": True,
        "exact_match": True,
        "differences": {},
    }


def _label(decision: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(decision.get("route_kind") or ""),
        str(decision.get("task_profile") or ""),
        str(decision.get("pipeline") or ""),
    )


def _precheck_pair(
    pair: dict[str, Any],
    *,
    policy_root: Path,
    existing_keys: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    checked: list[dict[str, Any]] = []
    errors: list[str] = []
    for member in pair["members"]:
        query = member["query"]
        pipeline_mode = member.get("pipeline_mode") or "auto"
        if _input_key(query, pipeline_mode) in existing_keys:
            errors.append(f"{member['member_id']}: input already exists in formal dataset")
        decision = compile_controller_decision(
            query,
            root=Path(policy_root),
            pipeline_mode=pipeline_mode,
        )
        if decision.get("route_kind") != member["expected_route"]:
            errors.append(
                f"{member['member_id']}: expected route {member['expected_route']!r}, "
                f"got {decision.get('route_kind')!r}"
            )
        if decision.get("task_profile") != member["expected_profile"]:
            errors.append(
                f"{member['member_id']}: expected profile {member['expected_profile']!r}, "
                f"got {decision.get('task_profile')!r}"
            )
        checked.append({**member, "decision": decision})
    if len({_label(item["decision"]) for item in checked}) < 2:
        errors.append("pair does not produce at least two distinct route/profile/pipeline labels")
    return checked, errors


def run_factory(
    *,
    dataset: Path = DEFAULT_DATASET,
    policy_root: Path = ROOT,
    queue_root: Path = ROOT,
    limit_pairs: int = 0,
    write: bool = False,
) -> dict[str, Any]:
    pairs = build_hard_negative_pairs()
    existing_keys = _existing_input_keys(Path(dataset))
    stats: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    skipped: list[dict[str, Any]] = []
    accepted_pairs: list[str] = []
    config = {
        "learning_queue_enabled": True,
        "agreement_sample_rate": 1.0,
        "max_records_per_day": max(500, len(pairs) * 4),
    }

    for pair in pairs[:limit_pairs or None]:
        stats["pairs_considered"] += 1
        checked, errors = _precheck_pair(pair, policy_root=Path(policy_root), existing_keys=existing_keys)
        if errors:
            stats["pairs_skipped"] += 1
            if len(skipped) < 50:
                skipped.append({"pair_id": pair["pair_id"], "errors": errors})
            continue
        stats["pairs_verified"] += 1
        accepted_pairs.append(pair["pair_id"])
        contrast_labels = sorted("/".join(_label(item["decision"])) for item in checked)
        for item in checked:
            decision = item["decision"]
            route_counts[str(decision.get("route_kind") or "unknown")] += 1
            stats["members_verified"] += 1
            if not write:
                stats["dry_run_candidates"] += 1
                continue
            query = item["query"]
            pipeline_mode = item.get("pipeline_mode") or "auto"
            model_input = compile_controller_example_input(
                query,
                root=Path(policy_root),
                pipeline_mode=pipeline_mode,
            )
            result = accumulate_learning_candidate(
                query,
                root=Path(queue_root),
                model_input=model_input,
                reference=decision,
                candidate=decision,
                comparison=_exact_comparison(),
                config=config,
                provenance={
                    "type": "data_factory",
                    "factory_kind": "hard_negative",
                    "factory_version": FACTORY_VERSION,
                    "source_split": "train",
                    "pair_id": pair["pair_id"],
                    "pair_size": len(checked),
                    "member_id": item["member_id"],
                    "expected_route": item["expected_route"],
                    "expected_profile": item["expected_profile"],
                    "contrast_labels": contrast_labels,
                },
                force_collect=True,
                priority_override="medium",
                collection_reasons_override=[
                    "factory_hard_negative",
                    "teacher_label_verified",
                    "minimal_pair",
                ],
                increment_duplicate_count=False,
            )
            stats[str(result.get("status") or "unknown")] += 1

    return {
        "schema_version": "uruk_controller_hard_negative_factory_report.v1",
        "factory_version": FACTORY_VERSION,
        "write": write,
        "source_split": "train",
        "available_pair_count": len(pairs),
        "limit_pairs": limit_pairs,
        "accepted_pairs": accepted_pairs,
        "stats": dict(sorted(stats.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "skipped_pairs": skipped,
    }


def _learning_records(queue_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    base = Path(queue_root) / "data" / "controller_learning"
    for status in STATUSES:
        directory = base / status
        if not directory.exists():
            continue
        for path in sorted(directory.glob("learn_*.json")):
            try:
                records.append((path, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                records.append((path, {"_load_error": True}))
    return records


def audit_hard_negative_queue(*, queue_root: Path = ROOT, policy_root: Path = ROOT) -> dict[str, Any]:
    groups: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    issues: list[dict[str, Any]] = []
    route_counts: Counter[str] = Counter()
    checked = 0
    for path, record in _learning_records(Path(queue_root)):
        provenance = record.get("provenance") or {}
        if provenance.get("factory_kind") != "hard_negative":
            continue
        pair_id = str(provenance.get("pair_id") or "")
        groups[pair_id].append((path, record))

    for pair_id, members in sorted(groups.items()):
        pair_errors: list[str] = []
        member_ids: set[str] = set()
        labels: set[tuple[str, str, str]] = set()
        expected_sizes: set[int] = set()
        for path, record in members:
            checked += 1
            provenance = record.get("provenance") or {}
            if record.get("_load_error"):
                pair_errors.append(f"{path.name}: invalid JSON")
                continue
            if provenance.get("type") != "data_factory":
                pair_errors.append(f"{path.name}: provenance type is not data_factory")
            if provenance.get("source_split") != "train":
                pair_errors.append(f"{path.name}: source split is not train")
            if provenance.get("factory_version") != FACTORY_VERSION:
                pair_errors.append(f"{path.name}: unexpected factory version")
            try:
                expected_sizes.add(int(provenance.get("pair_size") or 0))
            except (TypeError, ValueError):
                expected_sizes.add(0)
            member_id = str(provenance.get("member_id") or "")
            if not member_id:
                pair_errors.append(f"{path.name}: missing member_id")
            elif member_id in member_ids:
                pair_errors.append(f"{path.name}: duplicate member_id {member_id!r}")
            member_ids.add(member_id)

            reference = record.get("reference") or {}
            reference_errors = validate_controller_decision(reference)
            pair_errors.extend(f"{path.name}: {error}" for error in reference_errors)
            model_input = record.get("input") or {}
            query = str(model_input.get("user_input") or "")
            signals = model_input.get("runtime_signals") or {}
            current = compile_controller_decision(
                query,
                root=Path(policy_root),
                pipeline_mode=str(signals.get("pipeline_mode") or "auto"),
                selected_modes=list(signals.get("selected_modes") or []),
            )
            for key in CRITICAL_FIELDS:
                if current.get(key) != reference.get(key):
                    pair_errors.append(
                        f"{path.name}: current teacher changed {key}: "
                        f"{reference.get(key)!r} -> {current.get(key)!r}"
                    )
            if reference.get("route_kind") != provenance.get("expected_route"):
                pair_errors.append(f"{path.name}: reference route differs from expected route provenance")
            if reference.get("task_profile") != provenance.get("expected_profile"):
                pair_errors.append(f"{path.name}: reference profile differs from expected profile provenance")
            labels.add(_label(reference))
            route_counts[str(reference.get("route_kind") or "unknown")] += 1

        if len(expected_sizes) != 1 or not expected_sizes or next(iter(expected_sizes)) != len(members):
            pair_errors.append(
                f"pair is incomplete or has inconsistent size: expected={sorted(expected_sizes)}, actual={len(members)}"
            )
        if len(labels) < 2:
            pair_errors.append("pair has fewer than two distinct route/profile/pipeline labels")
        if pair_errors:
            issues.append({"pair_id": pair_id or "<missing>", "errors": pair_errors})

    return {
        "schema_version": "uruk_controller_hard_negative_audit.v1",
        "passed": not issues,
        "pair_count": len(groups),
        "checked": checked,
        "route_counts": dict(sorted(route_counts.items())),
        "issue_count": len(issues),
        "issues": issues[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and audit controller hard-negative minimal pairs.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--limit-pairs", type=int, default=0)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--audit-queue", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-report", default="")
    args = parser.parse_args()
    report = (
        audit_hard_negative_queue()
        if args.audit_queue
        else run_factory(
            dataset=Path(args.dataset),
            limit_pairs=max(0, args.limit_pairs),
            write=args.write,
        )
    )
    if args.write_report:
        path = Path(args.write_report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.audit_queue:
        status = "PASS" if report["passed"] else "FAIL"
        print(
            f"Controller Hard Negative audit {status}: "
            f"{report['pair_count']} pairs, {report['checked']} members, {report['issue_count']} issues"
        )
        print(f"  routes: {report['route_counts']}")
    else:
        mode = "WRITE" if args.write else "DRY RUN"
        print(f"Controller Hard Negative Factory {mode}: {report['stats']}")
        print(f"  routes: {report['route_counts']}")
        if report["skipped_pairs"]:
            print(f"  skipped pairs: {len(report['skipped_pairs'])}")
    return 0 if not args.audit_queue or report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
