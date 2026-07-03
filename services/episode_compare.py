"""Deterministic comparison for URUK harness episodes.

This module compares machine-readable harness episode JSON files. It does not
call an LLM and is intended for regression checks, upgrade reports, and prompt
change review.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EPISODE_DIR = ROOT / "data" / "harness_episodes"
SCHEMA_VERSION = "1.0"


def _get(data: Dict[str, Any], path: Iterable[str], default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _issue_counts(ep: Dict[str, Any]) -> Dict[str, int]:
    issues = _get(ep, ("context", "knowledge", "health", "summary", "issues"), {}) or {}
    out: Dict[str, int] = {}
    for key in ("P0", "P1", "P2", "P3"):
        try:
            out[key] = int(issues.get(key) or 0)
        except Exception:
            out[key] = 0
    return out


def _validators(ep: Dict[str, Any]) -> Dict[str, Any]:
    return ep.get("validators") or {}


def _coord_eval(ep: Dict[str, Any]) -> Dict[str, Any]:
    validators = _validators(ep)
    return validators.get("coordinate_output_eval") or validators.get("coordinate_eval") or {}


def _density_eval(ep: Dict[str, Any]) -> Dict[str, Any]:
    validators = _validators(ep)
    return validators.get("output_density_audit") or validators.get("density_audit") or {}


def _cost_metrics(ep: Dict[str, Any]) -> Dict[str, Any]:
    return (
        _get(ep, ("run", "cost_metrics"), {})
        or _get(ep, ("context", "dispatch", "cost_metrics"), {})
        or {}
    )


def _trace(ep: Dict[str, Any]) -> List[Dict[str, Any]]:
    trace = _get(ep, ("context", "knowledge", "trace"), []) or []
    return trace if isinstance(trace, list) else []


def _trace_doc_ids(ep: Dict[str, Any]) -> List[str]:
    ids = set()
    for entry in _trace(ep):
        for hit in entry.get("hits") or []:
            doc_id = hit.get("doc_id") or hit.get("source_file")
            if isinstance(doc_id, str) and doc_id:
                ids.add(doc_id)
    return sorted(ids)


def _trace_card_ids(ep: Dict[str, Any]) -> List[str]:
    ids = set()
    for entry in _trace(ep):
        for hit in entry.get("hits") or []:
            card_id = hit.get("card_id") or hit.get("id")
            if isinstance(card_id, str) and card_id:
                ids.add(card_id)
    return sorted(ids)


def _voice_error_flags(ep: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    voices = ep.get("voices") or {}
    for name, payload in voices.items():
        preview = str((payload or {}).get("preview") or "")
        if "[節點錯誤]" in preview or "[node error]" in preview.casefold():
            flags.append(str(name))
    return sorted(flags)


def _set_delta(left: Iterable[str], right: Iterable[str]) -> Dict[str, List[str]]:
    left_set = set(left)
    right_set = set(right)
    return {
        "added": sorted(right_set - left_set),
        "removed": sorted(left_set - right_set),
        "shared": sorted(left_set & right_set),
    }


def _episode_summary(ep: Dict[str, Any], path: Path) -> Dict[str, Any]:
    return {
        "episode_id": ep.get("episode_id") or path.stem,
        "path": str(path),
        "created_at": ep.get("created_at"),
        "timestamp": _get(ep, ("run", "timestamp")),
        "pipeline_mode": _get(ep, ("run", "pipeline_mode")),
        "selected_modes": _get(ep, ("run", "selected_modes"), []),
        "input_sha256": _get(ep, ("run", "input_sha256")),
        "input_preview": str(_get(ep, ("run", "input"), ""))[:160],
        "cost_metrics": _cost_metrics(ep),
    }


def load_episode(path: Path | str) -> Dict[str, Any]:
    """Load one harness episode JSON file."""
    episode_path = Path(path)
    return json.loads(episode_path.read_text(encoding="utf-8"))


def list_episode_paths(*, root: Path = ROOT, limit: Optional[int] = None) -> List[Path]:
    """Return harness episode JSON paths sorted newest first."""
    episode_dir = Path(root) / "data" / "harness_episodes"
    if not episode_dir.exists():
        return []
    paths = sorted(
        episode_dir.glob("**/*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return paths[:limit] if limit else paths


def resolve_episode(identifier: str | Path, *, root: Path = ROOT) -> Path:
    """Resolve an episode id, stem, relative path, or absolute path."""
    raw = Path(identifier)
    candidates = [
        raw,
        Path(root) / raw,
        Path(root) / "data" / raw,
        Path(root) / "data" / "harness_episodes" / raw,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    ident = str(identifier)
    for path in list_episode_paths(root=root):
        if path.stem == ident:
            return path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("episode_id") == ident:
                return path
        except Exception:
            continue
    raise FileNotFoundError(f"episode not found: {identifier}")


def latest_episode_pair(*, root: Path = ROOT) -> Tuple[Path, Path]:
    """Return the two newest episodes as (left_older, right_newer)."""
    paths = list_episode_paths(root=root, limit=2)
    if len(paths) < 2:
        raise FileNotFoundError("need at least two harness episodes")
    return paths[1], paths[0]


def compare_episodes(
    left_path: str | Path,
    right_path: str | Path,
    *,
    root: Path = ROOT,
) -> Dict[str, Any]:
    """Compare two harness episodes.

    `left` is the baseline/older episode; `right` is the candidate/newer
    episode. The returned payload is deterministic and JSON-serializable.
    """
    left_path = resolve_episode(left_path, root=root)
    right_path = resolve_episode(right_path, root=root)
    left = load_episode(left_path)
    right = load_episode(right_path)

    left_coord = _coord_eval(left)
    right_coord = _coord_eval(right)
    left_density = _density_eval(left)
    right_density = _density_eval(right)
    left_cost = _cost_metrics(left)
    right_cost = _cost_metrics(right)
    left_council = _get(left, ("validators", "council_decision"), {}) or {}
    right_council = _get(right, ("validators", "council_decision"), {}) or {}
    left_issues = _issue_counts(left)
    right_issues = _issue_counts(right)
    issue_delta = {key: right_issues.get(key, 0) - left_issues.get(key, 0) for key in ("P0", "P1", "P2", "P3")}

    left_score = _num(left_coord.get("score"))
    right_score = _num(right_coord.get("score"))
    coordinate_score_delta = None if left_score is None or right_score is None else round(right_score - left_score, 4)
    left_missing = int(left_coord.get("missing_count") or 0)
    right_missing = int(right_coord.get("missing_count") or 0)
    density_errors_delta = len(right_density.get("errors") or []) - len(left_density.get("errors") or [])
    trace_count_delta = len(_trace(right)) - len(_trace(left))
    left_model_calls = _num(left_cost.get("estimated_model_calls"))
    right_model_calls = _num(right_cost.get("estimated_model_calls"))
    model_call_delta = None if left_model_calls is None or right_model_calls is None else int(right_model_calls - left_model_calls)
    left_api_calls = _num(left_cost.get("estimated_api_model_calls"))
    right_api_calls = _num(right_cost.get("estimated_api_model_calls"))
    api_call_delta = None if left_api_calls is None or right_api_calls is None else int(right_api_calls - left_api_calls)
    left_context_tokens = _num(left_cost.get("estimated_context_tokens"))
    right_context_tokens = _num(right_cost.get("estimated_context_tokens"))
    context_token_delta = None if left_context_tokens is None or right_context_tokens is None else int(right_context_tokens - left_context_tokens)

    left_docs = _trace_doc_ids(left)
    right_docs = _trace_doc_ids(right)
    left_cards = _trace_card_ids(left)
    right_cards = _trace_card_ids(right)
    left_voice_errors = _voice_error_flags(left)
    right_voice_errors = _voice_error_flags(right)

    regressions: List[str] = []
    improvements: List[str] = []
    changes: List[str] = []

    left_clean = bool(_get(left, ("context", "knowledge", "health", "clean"), False))
    right_clean = bool(_get(right, ("context", "knowledge", "health", "clean"), False))
    if left_clean and not right_clean:
        regressions.append("knowledge_clean_regressed")
    elif not left_clean and right_clean:
        improvements.append("knowledge_clean_recovered")

    for severity in ("P0", "P1"):
        if issue_delta[severity] > 0:
            regressions.append(f"knowledge_{severity}_increased")
        elif issue_delta[severity] < 0:
            improvements.append(f"knowledge_{severity}_decreased")

    if coordinate_score_delta is not None:
        if coordinate_score_delta < 0:
            regressions.append("coordinate_score_decreased")
        elif coordinate_score_delta > 0:
            improvements.append("coordinate_score_increased")
    missing_delta = right_missing - left_missing
    if missing_delta > 0:
        regressions.append("coordinate_missing_increased")
    elif missing_delta < 0:
        improvements.append("coordinate_missing_decreased")

    if bool(left_density.get("audit_ran")) and not bool(right_density.get("audit_ran")):
        regressions.append("density_audit_stopped_running")
    if density_errors_delta > 0:
        regressions.append("density_errors_increased")
    elif density_errors_delta < 0:
        improvements.append("density_errors_decreased")

    if left_council.get("verdict") != right_council.get("verdict"):
        changes.append("council_verdict_changed")
    if left_council.get("_parse_error") != right_council.get("_parse_error"):
        changes.append("council_parse_error_changed")
        if right_council.get("_parse_error") and not left_council.get("_parse_error"):
            regressions.append("council_parse_error_introduced")

    newly_broken_voices = sorted(set(right_voice_errors) - set(left_voice_errors))
    recovered_voices = sorted(set(left_voice_errors) - set(right_voice_errors))
    if newly_broken_voices:
        regressions.append("node_errors_introduced")
    if recovered_voices:
        improvements.append("node_errors_recovered")

    if _get(left, ("run", "input_sha256")) != _get(right, ("run", "input_sha256")):
        changes.append("input_changed")
    if _get(left, ("run", "pipeline_mode")) != _get(right, ("run", "pipeline_mode")):
        changes.append("pipeline_mode_changed")
    same_input = _get(left, ("run", "input_sha256")) == _get(right, ("run", "input_sha256"))
    if same_input:
        if api_call_delta is not None:
            if api_call_delta > 0:
                regressions.append("api_model_calls_increased")
            elif api_call_delta < 0:
                improvements.append("api_model_calls_decreased")
        if model_call_delta is not None:
            if model_call_delta > 0:
                regressions.append("model_calls_increased")
            elif model_call_delta < 0:
                improvements.append("model_calls_decreased")
        if context_token_delta is not None:
            if context_token_delta > 0:
                regressions.append("context_tokens_increased")
            elif context_token_delta < 0:
                improvements.append("context_tokens_decreased")

    voice_sha = {}
    for name in ("father", "son", "spirit", "council"):
        voice_sha[name] = {
            "changed": _get(left, ("voices", name, "sha256")) != _get(right, ("voices", name, "sha256")),
            "left": _get(left, ("voices", name, "sha256")),
            "right": _get(right, ("voices", name, "sha256")),
        }

    status = "regressed" if regressions else ("improved" if improvements else ("changed" if changes else "equivalent"))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "ok": not regressions,
        "left": _episode_summary(left, left_path),
        "right": _episode_summary(right, right_path),
        "metrics": {
            "coordinate_score": {"left": left_score, "right": right_score, "delta": coordinate_score_delta},
            "coordinate_missing_count": {"left": left_missing, "right": right_missing, "delta": missing_delta},
            "coordinate_use": {"left": left_coord.get("coordinate_use"), "right": right_coord.get("coordinate_use")},
            "knowledge_clean": {"left": left_clean, "right": right_clean},
            "knowledge_issue_delta": issue_delta,
            "knowledge_trace_count": {"left": len(_trace(left)), "right": len(_trace(right)), "delta": trace_count_delta},
            "density_audit_ran": {"left": bool(left_density.get("audit_ran")), "right": bool(right_density.get("audit_ran"))},
            "density_errors": {
                "left": len(left_density.get("errors") or []),
                "right": len(right_density.get("errors") or []),
                "delta": density_errors_delta,
            },
            "council_verdict": {"left": left_council.get("verdict"), "right": right_council.get("verdict")},
            "father_paused": {
                "left": bool(_get(left, ("validators", "father_paused"), False)),
                "right": bool(_get(right, ("validators", "father_paused"), False)),
            },
            "node_errors": {"left": left_voice_errors, "right": right_voice_errors},
            "cost_class": {
                "left": left_cost.get("estimated_cost_class"),
                "right": right_cost.get("estimated_cost_class"),
            },
            "model_calls": {"left": left_model_calls, "right": right_model_calls, "delta": model_call_delta},
            "api_model_calls": {"left": left_api_calls, "right": right_api_calls, "delta": api_call_delta},
            "context_tokens": {"left": left_context_tokens, "right": right_context_tokens, "delta": context_token_delta},
        },
        "diffs": {
            "trace_doc_ids": _set_delta(left_docs, right_docs),
            "trace_card_ids": _set_delta(left_cards, right_cards),
            "voice_sha256": voice_sha,
        },
        "regressions": sorted(set(regressions)),
        "improvements": sorted(set(improvements)),
        "changes": sorted(set(changes)),
    }


def compare_latest(*, root: Path = ROOT) -> Dict[str, Any]:
    left, right = latest_episode_pair(root=root)
    return compare_episodes(left, right, root=root)
