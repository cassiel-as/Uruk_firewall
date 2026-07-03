"""Curate controller-learning candidates into reviewable, atomic batches.

The curator ranks useful candidates, surfaces quality blockers, and keeps hard
negative pairs together. It never approves data while preparing a packet.
Operators must explicitly edit unit-level decisions and run the apply command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.controller_policy import compile_controller_decision  # noqa: E402
from services.encoding_audit import analyze_text  # noqa: E402
from training.controller_learning_queue import review  # noqa: E402
from training.dataset_validator import validate_controller_decision  # noqa: E402


BASE = ROOT / "data" / "controller_learning"
CRITICAL_FIELDS = (
    "route_kind",
    "task_profile",
    "pipeline",
    "tool_permission",
    "escalation_required",
)
PRIORITY_SCORE = {"critical": 120.0, "high": 95.0, "medium": 65.0, "low": 25.0}


def _load_pending(base: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pending = Path(base) / "pending"
    if not pending.exists():
        return records
    for path in sorted(pending.glob("learn_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            records.append({
                "candidate_id": path.stem,
                "status": "pending",
                "_path": str(path),
                "_load_error": f"{type(exc).__name__}: {exc}",
            })
            continue
        record["_path"] = str(path)
        records.append(record)
    return records


def _teacher_decision(record: dict[str, Any], *, policy_root: Path) -> dict[str, Any]:
    model_input = record.get("input") or {}
    signals = model_input.get("runtime_signals") or {}
    return compile_controller_decision(
        str(model_input.get("user_input") or ""),
        root=Path(policy_root),
        pipeline_mode=str(signals.get("pipeline_mode") or "auto"),
        selected_modes=list(signals.get("selected_modes") or []),
    )


def assess_record(record: dict[str, Any], *, policy_root: Path = ROOT) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if record.get("_load_error"):
        blockers.append("invalid_json")
        return {"blockers": blockers, "warnings": warnings, "teacher": None}
    if record.get("status") != "pending":
        blockers.append("not_pending")
    query = str((record.get("input") or {}).get("user_input") or "")
    if not query:
        blockers.append("empty_input")
    encoding = analyze_text(query)
    blockers.extend(f"encoding.{issue['code']}" for issue in encoding.get("issues") or [])
    if record.get("redactions"):
        warnings.append("contains_redactions")
    reference = record.get("reference") or {}
    blockers.extend(f"reference.{error}" for error in validate_controller_decision(reference))
    teacher = None
    if query and not blockers:
        teacher = _teacher_decision(record, policy_root=Path(policy_root))
        for key in CRITICAL_FIELDS:
            if teacher.get(key) != reference.get(key):
                blockers.append(f"teacher_changed.{key}")
    comparison = record.get("latest_comparison") or record.get("comparison") or {}
    if not comparison.get("schema_valid", True):
        blockers.append("shadow_candidate_schema_invalid")
    if not comparison.get("route_match", True):
        warnings.append("shadow_route_disagreement")
    if not comparison.get("authority_match", True):
        warnings.append("shadow_authority_disagreement")
    if not comparison.get("escalation_match", True):
        warnings.append("shadow_escalation_disagreement")
    return {
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "teacher": teacher,
        "encoding": encoding,
    }


def _record_summary(record: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    reference = record.get("reference") or {}
    provenance = record.get("provenance") or {}
    signals = (record.get("input") or {}).get("runtime_signals") or {}
    return {
        "candidate_id": record.get("candidate_id"),
        "priority": record.get("priority"),
        "query": str((record.get("input") or {}).get("user_input") or ""),
        "pipeline_mode": str(signals.get("pipeline_mode") or "auto"),
        "route_kind": reference.get("route_kind"),
        "task_profile": reference.get("task_profile"),
        "pipeline": reference.get("pipeline"),
        "tool_permission": reference.get("tool_permission"),
        "escalation_required": reference.get("escalation_required"),
        "collection_reasons": list(record.get("collection_reasons") or []),
        "provenance": provenance,
        "blockers": assessment["blockers"],
        "warnings": assessment["warnings"],
    }


def _unit_score(
    members: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    route_counts: Counter[str],
    hard_negative: bool,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if any(assessment["blockers"] for _, assessment in members):
        reasons.append("quality_blocker_requires_rejection")
        return 1000.0, reasons
    score = max(PRIORITY_SCORE.get(str(record.get("priority") or ""), 0.0) for record, _ in members)
    if hard_negative:
        score += 80.0
        reasons.append("complete_hard_negative_pair")
    if any((record.get("provenance") or {}).get("type") != "data_factory" for record, _ in members):
        score += 45.0
        reasons.append("real_shadow_observation")
    if any(assessment["warnings"] for _, assessment in members):
        score += 20.0
        reasons.append("disagreement_or_privacy_warning")
    routes = {str((record.get("reference") or {}).get("route_kind") or "unknown") for record, _ in members}
    rarity = sum(30.0 / math.sqrt(max(1, route_counts[route])) for route in routes)
    score += rarity
    reasons.append("route_coverage")
    return round(score, 3), reasons


def build_review_units(
    *,
    base: Path = BASE,
    policy_root: Path = ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = _load_pending(Path(base))
    route_counts: Counter[str] = Counter(
        str((record.get("reference") or {}).get("route_kind") or "unknown")
        for record in records
        if not record.get("_load_error")
    )
    assessments = {
        str(record.get("candidate_id") or ""): assess_record(record, policy_root=Path(policy_root))
        for record in records
    }
    pair_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    singles: list[dict[str, Any]] = []
    for record in records:
        provenance = record.get("provenance") or {}
        pair_id = str(provenance.get("pair_id") or "")
        if provenance.get("factory_kind") == "hard_negative" and pair_id:
            pair_groups[pair_id].append(record)
        else:
            singles.append(record)

    units: list[dict[str, Any]] = []
    for pair_id, members in sorted(pair_groups.items()):
        assessed = [(record, assessments[str(record.get("candidate_id") or "")]) for record in members]
        expected_sizes = {
            int((record.get("provenance") or {}).get("pair_size") or 0)
            for record in members
        }
        unit_blockers: list[str] = []
        if len(expected_sizes) != 1 or next(iter(expected_sizes), 0) != len(members):
            unit_blockers.append("incomplete_hard_negative_pair")
        labels = {
            (
                (record.get("reference") or {}).get("route_kind"),
                (record.get("reference") or {}).get("task_profile"),
                (record.get("reference") or {}).get("pipeline"),
            )
            for record in members
        }
        if len(labels) < 2:
            unit_blockers.append("collapsed_hard_negative_pair")
        score, reasons = _unit_score(assessed, route_counts=route_counts, hard_negative=True)
        blockers = sorted(set(unit_blockers + [item for _, assessment in assessed for item in assessment["blockers"]]))
        if unit_blockers:
            score = 1000.0
            reasons = ["quality_blocker_requires_rejection"]
        units.append({
            "review_unit_id": f"pair:{pair_id}",
            "unit_type": "hard_negative_pair",
            "pair_id": pair_id,
            "candidate_count": len(members),
            "candidate_ids": sorted(str(record.get("candidate_id") or "") for record in members),
            "score": score,
            "selection_reasons": reasons,
            "recommended_action": "reject" if blockers else "approve",
            "decision": "pending",
            "reviewer_note": "",
            "blockers": blockers,
            "members": [
                _record_summary(record, assessment)
                for record, assessment in sorted(assessed, key=lambda item: str(item[0].get("candidate_id") or ""))
            ],
        })

    for record in singles:
        assessment = assessments[str(record.get("candidate_id") or "")]
        score, reasons = _unit_score([(record, assessment)], route_counts=route_counts, hard_negative=False)
        blockers = assessment["blockers"]
        units.append({
            "review_unit_id": f"candidate:{record.get('candidate_id')}",
            "unit_type": "single",
            "pair_id": None,
            "candidate_count": 1,
            "candidate_ids": [record.get("candidate_id")],
            "score": score,
            "selection_reasons": reasons,
            "recommended_action": "reject" if blockers else "approve",
            "decision": "pending",
            "reviewer_note": "",
            "blockers": blockers,
            "members": [_record_summary(record, assessment)],
        })

    units.sort(key=lambda item: (-float(item["score"]), str(item["review_unit_id"])))
    return units, {
        "pending_record_count": len(records),
        "review_unit_count": len(units),
        "hard_negative_pair_count": len(pair_groups),
        "route_counts": dict(sorted(route_counts.items())),
        "blocked_unit_count": sum(bool(unit["blockers"]) for unit in units),
    }


def prepare_review_packet(
    *,
    base: Path = BASE,
    policy_root: Path = ROOT,
    max_candidates: int = 80,
) -> dict[str, Any]:
    units, queue_summary = build_review_units(base=Path(base), policy_root=Path(policy_root))
    selected: list[dict[str, Any]] = []
    selected_count = 0
    for unit in units:
        size = int(unit["candidate_count"])
        if selected and selected_count + size > max(1, max_candidates):
            continue
        selected.append(unit)
        selected_count += size
        if selected_count >= max(1, max_candidates):
            break
    material = json.dumps(
        {
            "candidate_ids": [candidate_id for unit in selected for candidate_id in unit["candidate_ids"]],
            "max_candidates": max_candidates,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    packet_id = "review_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    route_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    for unit in selected:
        action_counts[unit["recommended_action"]] += int(unit["candidate_count"])
        route_counts.update(str(member.get("route_kind") or "unknown") for member in unit["members"])
    return {
        "schema_version": "uruk_controller_review_packet.v1",
        "packet_id": packet_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_status": "pending",
        "policy": {
            "max_candidates": max_candidates,
            "hard_negative_pairs_are_atomic": True,
            "preparation_never_approves": True,
            "blocked_units_cannot_be_approved": True,
            "approved_factory_split": "train",
        },
        "queue_summary": queue_summary,
        "selection_summary": {
            "unit_count": len(selected),
            "candidate_count": selected_count,
            "route_counts": dict(sorted(route_counts.items())),
            "recommended_action_counts": dict(sorted(action_counts.items())),
        },
        "units": selected,
    }


def packet_markdown(packet: dict[str, Any]) -> str:
    summary = packet.get("selection_summary") or {}
    lines = [
        f"# Controller Review Packet {packet.get('packet_id')}",
        "",
        f"- Candidates: {summary.get('candidate_count', 0)}",
        f"- Review units: {summary.get('unit_count', 0)}",
        f"- Routes: `{json.dumps(summary.get('route_counts') or {}, ensure_ascii=False, sort_keys=True)}`",
        "- Decisions remain `pending` until the JSON packet is explicitly edited and applied.",
        "",
    ]
    for index, unit in enumerate(packet.get("units") or [], start=1):
        lines.extend([
            f"## {index}. {unit.get('review_unit_id')}",
            "",
            f"- Recommended: **{unit.get('recommended_action')}**",
            f"- Decision: `{unit.get('decision')}`",
            f"- Score: {unit.get('score')}",
            f"- Blockers: `{', '.join(unit.get('blockers') or []) or 'none'}`",
        ])
        for member in unit.get("members") or []:
            lines.extend([
                f"- `{member.get('candidate_id')}` `{member.get('route_kind')}/{member.get('task_profile')}`",
                f"  - {member.get('query')}",
            ])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_review_packet(packet: dict[str, Any], *, json_path: Path, markdown_path: Path | None = None) -> None:
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    if markdown_path is not None:
        markdown_path = Path(markdown_path)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(packet_markdown(packet), encoding="utf-8")


def audit_review_packet(
    packet: dict[str, Any],
    *,
    base: Path = BASE,
    policy_root: Path = ROOT,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    pending = {str(record.get("candidate_id") or ""): record for record in _load_pending(Path(base))}
    pending_pairs: dict[str, set[str]] = defaultdict(set)
    for candidate_id, record in pending.items():
        provenance = record.get("provenance") or {}
        pair_id = str(provenance.get("pair_id") or "")
        if provenance.get("factory_kind") == "hard_negative" and pair_id:
            pending_pairs[pair_id].add(candidate_id)
    seen: set[str] = set()
    checked = 0
    for unit in packet.get("units") or []:
        unit_errors: list[str] = []
        ids = [str(item) for item in (unit.get("candidate_ids") or [])]
        if len(ids) != len(set(ids)):
            unit_errors.append("duplicate candidate ids inside unit")
        if int(unit.get("candidate_count") or 0) != len(ids):
            unit_errors.append("candidate_count does not match candidate_ids")
        if unit.get("unit_type") == "hard_negative_pair" and len(ids) < 2:
            unit_errors.append("hard-negative unit must contain a complete pair")
        if unit.get("unit_type") == "hard_negative_pair":
            pair_id = str(unit.get("pair_id") or "")
            current_pair_ids = pending_pairs.get(pair_id, set())
            if set(ids) != current_pair_ids:
                unit_errors.append(
                    f"hard-negative unit differs from current pending pair: "
                    f"packet={sorted(ids)}, current={sorted(current_pair_ids)}"
                )
        for candidate_id in ids:
            checked += 1
            if candidate_id in seen:
                unit_errors.append(f"{candidate_id}: appears in multiple units")
            seen.add(candidate_id)
            record = pending.get(candidate_id)
            if record is None:
                unit_errors.append(f"{candidate_id}: no longer pending")
                continue
            assessment = assess_record(record, policy_root=Path(policy_root))
            packet_member = next(
                (member for member in (unit.get("members") or []) if member.get("candidate_id") == candidate_id),
                None,
            )
            if packet_member is None:
                unit_errors.append(f"{candidate_id}: missing packet member")
            elif sorted(packet_member.get("blockers") or []) != assessment["blockers"]:
                unit_errors.append(f"{candidate_id}: blocker state changed")
        if unit_errors:
            issues.append({"review_unit_id": unit.get("review_unit_id"), "errors": unit_errors})
    return {
        "schema_version": "uruk_controller_review_packet_audit.v1",
        "passed": not issues,
        "packet_id": packet.get("packet_id"),
        "checked": checked,
        "issue_count": len(issues),
        "issues": issues,
    }


def apply_review_packet(
    packet: dict[str, Any],
    *,
    reviewer: str,
    base: Path = BASE,
    policy_root: Path = ROOT,
) -> dict[str, Any]:
    audit = audit_review_packet(packet, base=Path(base), policy_root=Path(policy_root))
    if not audit["passed"]:
        raise ValueError("Review packet audit failed before apply.")
    pending = {str(record.get("candidate_id") or ""): record for record in _load_pending(Path(base))}
    applied: list[dict[str, Any]] = []
    skipped = 0
    for unit in packet.get("units") or []:
        decision = str(unit.get("decision") or "pending")
        if decision == "pending":
            skipped += int(unit.get("candidate_count") or 0)
            continue
        if decision not in {"approved", "rejected"}:
            raise ValueError(f"Unsupported decision {decision!r} for {unit.get('review_unit_id')}")
        if decision == "approved" and unit.get("blockers"):
            raise ValueError(f"Blocked unit cannot be approved: {unit.get('review_unit_id')}")
        ids = [str(item) for item in (unit.get("candidate_ids") or [])]
        for candidate_id in ids:
            record = pending[candidate_id]
            assessment = assess_record(record, policy_root=Path(policy_root))
            if decision == "approved" and assessment["blockers"]:
                raise ValueError(f"Blocked candidate cannot be approved: {candidate_id}")
        note = str(unit.get("reviewer_note") or f"review packet {packet.get('packet_id')}")
        for candidate_id in ids:
            applied.append(review(
                candidate_id,
                decision,
                reviewer=reviewer,
                split="train",
                note=note,
                base=Path(base),
            ))
    return {
        "schema_version": "uruk_controller_review_packet_apply.v1",
        "packet_id": packet.get("packet_id"),
        "applied_count": len(applied),
        "skipped_pending_count": skipped,
        "results": applied,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Curate and apply review-gated controller candidate batches.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--max-candidates", type=int, default=80)
    prepare.add_argument("--output-json", default="data/reports/controller_review_packet_001.json")
    prepare.add_argument("--output-md", default="data/reports/controller_review_packet_001.md")
    prepare.add_argument("--json", action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("packet")
    audit.add_argument("--json", action="store_true")
    apply = sub.add_parser("apply")
    apply.add_argument("packet")
    apply.add_argument("--reviewer", required=True)
    apply.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.command == "prepare":
        result = prepare_review_packet(max_candidates=max(1, args.max_candidates))
        write_review_packet(result, json_path=Path(args.output_json), markdown_path=Path(args.output_md))
    else:
        packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
        result = (
            audit_review_packet(packet)
            if args.command == "audit"
            else apply_review_packet(packet, reviewer=args.reviewer)
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "prepare":
        summary = result["selection_summary"]
        print(
            f"Controller review packet prepared: {summary['unit_count']} units, "
            f"{summary['candidate_count']} candidates"
        )
        print(f"  recommended: {summary['recommended_action_counts']}")
    elif args.command == "audit":
        status = "PASS" if result["passed"] else "FAIL"
        print(f"Controller review packet audit {status}: {result['checked']} checked, {result['issue_count']} issues")
    else:
        print(f"Controller review packet applied: {result['applied_count']} moved, {result['skipped_pending_count']} pending")
    return 0 if args.command != "audit" or result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
