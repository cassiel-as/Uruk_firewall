"""Privacy-gated accumulation for controller shadow learning cases."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from training.dataset_validator import validate_controller_decision


SCHEMA_VERSION = "uruk_controller_learning_candidate.v1"
STATUSES = ("pending", "approved", "rejected")
_WRITE_LOCK = threading.Lock()
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"\bhttps?://[^\s<>'\"]+", re.IGNORECASE)
_WINDOWS_USER_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+\\[^\s<>'\"]*")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\s<>'\"]+")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\[^\s<>'\"]+")
_UNIX_HOME_PATH_RE = re.compile(r"(?<!\w)/(?:home|Users)/[^/\s]+/[^\s<>'\"]*")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|key|access[_ -]?token|password|passwd|secret)\s*[:=]\s*[^\s,;]+"
)
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b")


def sanitize_controller_input(query: str) -> tuple[str, list[str]]:
    """Remove common direct identifiers and credentials while retaining intent."""
    value = str(query or "")[:12000]
    redactions: list[str] = []
    substitutions = (
        (_BEARER_RE, "Bearer [SECRET]", "bearer_secret"),
        (_SECRET_ASSIGNMENT_RE, r"\1=[SECRET]", "secret_assignment"),
        (_EMAIL_RE, "[EMAIL]", "email"),
        (_URL_RE, "[URL]", "url"),
        (_WINDOWS_USER_PATH_RE, "[LOCAL_PATH]", "windows_user_path"),
        (_WINDOWS_PATH_RE, "[LOCAL_PATH]", "windows_path"),
        (_UNC_PATH_RE, "[LOCAL_PATH]", "unc_path"),
        (_UNIX_HOME_PATH_RE, "[LOCAL_PATH]", "unix_home_path"),
        (_IP_RE, "[IP_ADDRESS]", "ip_address"),
        (_CARD_RE, "[PAYMENT_NUMBER]", "payment_number"),
        (_LONG_TOKEN_RE, "[LONG_TOKEN]", "long_token"),
    )
    for pattern, replacement, label in substitutions:
        value, count = pattern.subn(replacement, value)
        if count:
            redactions.append(label)
    value = " ".join(value.split())
    return value[:4000], sorted(set(redactions))


def _fingerprint(query: str, model_input: dict[str, Any]) -> str:
    signals = model_input.get("runtime_signals") or {}
    material = {
        "query": " ".join(query.casefold().split()),
        "pipeline_mode": signals.get("pipeline_mode"),
        "selected_modes": signals.get("selected_modes") or [],
    }
    digest = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return "learn_" + digest[:20]


def _priority(comparison: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not comparison.get("schema_valid", False):
        reasons.append("schema_invalid")
    if not comparison.get("authority_match", False):
        reasons.append("authority_disagreement")
    if not comparison.get("escalation_match", False):
        reasons.append("escalation_disagreement")
    if not comparison.get("route_match", False):
        reasons.append("route_disagreement")
    if comparison.get("differences"):
        reasons.append("decision_difference")
    if {"schema_invalid", "authority_disagreement", "escalation_disagreement"}.intersection(reasons):
        return "critical", reasons
    if "route_disagreement" in reasons:
        return "high", reasons
    if "decision_difference" in reasons:
        return "medium", reasons
    return "low", ["sampled_agreement"]


def should_collect_candidate(
    candidate_id: str,
    comparison: dict[str, Any],
    *,
    agreement_sample_rate: float,
) -> bool:
    if (
        not comparison.get("schema_valid", False)
        or not comparison.get("route_match", False)
        or not comparison.get("authority_match", False)
        or not comparison.get("escalation_match", False)
        or bool(comparison.get("differences"))
    ):
        return True
    rate = max(0.0, min(1.0, float(agreement_sample_rate)))
    bucket = int(hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < rate


def _all_candidate_paths(root: Path) -> list[Path]:
    base = Path(root) / "data" / "controller_learning"
    paths: list[Path] = []
    for status in STATUSES:
        directory = base / status
        if directory.exists():
            paths.extend(directory.glob("learn_*.json"))
    return paths


def learning_queue_summary(root: Path) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    occurrences = 0
    for path in _all_candidate_paths(root):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status_counts[path.parent.name] += 1
        priority_counts[str(record.get("priority") or "unknown")] += 1
        reason_counts.update(str(item) for item in (record.get("collection_reasons") or []))
        occurrences += int(record.get("occurrence_count") or 1)
    return {
        "schema_version": "uruk_controller_learning_summary.v1",
        "record_count": sum(status_counts.values()),
        "occurrence_count": occurrences,
        "status_counts": dict(sorted(status_counts.items())),
        "priority_counts": dict(sorted(priority_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def accumulate_learning_candidate(
    query: str,
    *,
    root: Path,
    model_input: dict[str, Any],
    reference: dict[str, Any],
    candidate: dict[str, Any],
    comparison: dict[str, Any],
    config: dict[str, Any],
    provenance: dict[str, Any] | None = None,
    force_collect: bool = False,
    priority_override: str = "",
    collection_reasons_override: list[str] | None = None,
    increment_duplicate_count: bool = True,
) -> dict[str, Any]:
    """Write or update one privacy-minimised candidate without approving it."""
    if not config.get("learning_queue_enabled", False):
        return {"status": "disabled"}
    sanitized_query, redactions = sanitize_controller_input(query)
    if not sanitized_query:
        return {"status": "skipped_empty"}

    sanitized_input = json.loads(json.dumps(model_input, ensure_ascii=False))
    sanitized_input["user_input"] = sanitized_query
    signals = sanitized_input.get("runtime_signals") or {}
    signals["text_length"] = len(sanitized_query)
    sanitized_input["runtime_signals"] = signals
    candidate_id = _fingerprint(sanitized_query, sanitized_input)
    if not force_collect and not should_collect_candidate(
        candidate_id,
        comparison,
        agreement_sample_rate=float(config.get("agreement_sample_rate") or 0.0),
    ):
        return {"status": "not_sampled", "candidate_id": candidate_id}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    priority, collection_reasons = _priority(comparison)
    if priority_override in {"critical", "high", "medium", "low"}:
        priority = priority_override
    if collection_reasons_override:
        collection_reasons = list(dict.fromkeys(str(item) for item in collection_reasons_override if item))
    base = Path(root) / "data" / "controller_learning"
    pending_dir = base / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    max_per_day = max(1, int(config.get("max_records_per_day") or 500))

    with _WRITE_LOCK:
        existing_path = next(
            (path for path in _all_candidate_paths(root) if path.stem == candidate_id),
            None,
        )
        if existing_path is not None:
            try:
                record = json.loads(existing_path.read_text(encoding="utf-8"))
                record["last_seen_at"] = now
                if increment_duplicate_count:
                    record["occurrence_count"] = int(record.get("occurrence_count") or 1) + 1
                record["latest_comparison"] = comparison
                if provenance and not record.get("provenance"):
                    record["provenance"] = provenance
                existing_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                return {
                    "status": "duplicate_updated" if increment_duplicate_count else "duplicate_unchanged",
                    "candidate_id": candidate_id,
                    "record_status": existing_path.parent.name,
                    "occurrence_count": record["occurrence_count"],
                }
            except (OSError, json.JSONDecodeError):
                pass

        today = now[:10]
        limit_scope = str((provenance or {}).get("type") or "shadow")
        today_count = 0
        for path in _all_candidate_paths(root):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                record_scope = str((record.get("provenance") or {}).get("type") or "shadow")
                today_count += int(
                    str(record.get("created_at") or "").startswith(today)
                    and record_scope == limit_scope
                )
            except (OSError, json.JSONDecodeError):
                continue
        if today_count >= max_per_day:
            return {
                "status": "daily_limit",
                "candidate_id": candidate_id,
                "daily_count": today_count,
                "limit_scope": limit_scope,
            }

        record = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "status": "pending",
            "priority": priority,
            "collection_reasons": collection_reasons,
            "created_at": now,
            "last_seen_at": now,
            "occurrence_count": 1,
            "query_sha256": hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest(),
            "redactions": redactions,
            "input": sanitized_input,
            "reference": reference,
            "candidate": candidate,
            "comparison": comparison,
            "latest_comparison": comparison,
            "provenance": provenance,
            "review": None,
        }
        schema_errors = validate_controller_decision(reference)
        if schema_errors:
            return {"status": "skipped_invalid_reference", "candidate_id": candidate_id, "errors": schema_errors}
        path = pending_dir / f"{candidate_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "collected", "candidate_id": candidate_id, "priority": priority, "redactions": redactions}
