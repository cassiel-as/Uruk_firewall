"""Persistent forecast revision ledger for the World Geo Timeline.

Each geotimeline run can append a compact, reproducible summary. The ledger
records how audited news moved scenario weights without storing full articles.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = APP_ROOT / "data" / "runtime" / "world_forecast_revisions.jsonl"
SCHEMA_VERSION = "world_forecast_revision.v1"
_LEDGER_LOCK = threading.Lock()


def _stable_revision_id(payload: Dict[str, Any]) -> str:
    correction = payload.get("forecast_correction") or {}
    news = payload.get("news_filter") or {}
    material = json.dumps(
        {
            "input_text": payload.get("input_text") or "",
            "horizon": payload.get("horizon") or "",
            "generated_at": payload.get("generated_at") or "",
            "corrected": correction.get("corrected") or {},
            "coordinates": news.get("coordinates") or [],
            "ratings": news.get("ratings") or {},
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "wrev_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def build_revision(payload: Dict[str, Any]) -> Dict[str, Any]:
    correction = payload.get("forecast_correction") or {}
    news = payload.get("news_filter") or {}
    graph = payload.get("graph") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "revision_id": _stable_revision_id(payload),
        "generated_at": str(payload.get("generated_at") or ""),
        "input_text": str(payload.get("input_text") or ""),
        "horizon": str(payload.get("horizon") or "medium"),
        "baseline": correction.get("baseline") or {},
        "corrected": correction.get("corrected") or {},
        "scenario_deltas": correction.get("scenario_deltas") or {},
        "correction_strength": str(correction.get("correction_strength") or "weak"),
        "max_absolute_shift": float(correction.get("max_absolute_shift") or 0.0),
        "news_summary": {
            "source_count": int(news.get("source_count") or 0),
            "coordinate_count": int(news.get("coordinate_count") or 0),
            "coordinates": list(news.get("coordinates") or []),
            "ratings": dict(news.get("ratings") or {}),
            "flags": list(news.get("flags") or []),
        },
        "graph_summary": {
            "event_count": int(graph.get("event_count") or len(payload.get("events") or [])),
            "link_count": int(graph.get("link_count") or len(payload.get("links") or [])),
            "layer_counts": dict(graph.get("layer_counts") or {}),
        },
    }


def append_revision(
    payload: Dict[str, Any],
    *,
    path: Optional[Path] = None,
    max_entries: int = 300,
) -> Dict[str, Any]:
    ledger_path = Path(path) if path else DEFAULT_PATH
    revision = build_revision(payload)
    with _LEDGER_LOCK:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        revisions = load_revisions(path=ledger_path, limit=max_entries)
        if any(item.get("revision_id") == revision["revision_id"] for item in revisions):
            return revision
        revisions.append(revision)
        revisions = revisions[-max(1, max_entries) :]
        temp_path = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
        temp_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in revisions),
            encoding="utf-8",
        )
        temp_path.replace(ledger_path)
    return revision


def load_revisions(
    *,
    query: str = "",
    path: Optional[Path] = None,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    ledger_path = Path(path) if path else DEFAULT_PATH
    if not ledger_path.exists():
        return []
    needle = query.strip().lower()
    revisions: List[Dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if needle and needle not in str(item.get("input_text") or "").lower():
            continue
        revisions.append(item)
    revisions.sort(key=lambda item: str(item.get("generated_at") or ""))
    return revisions[-max(1, min(int(limit), 300)) :]


__all__ = ["SCHEMA_VERSION", "append_revision", "build_revision", "load_revisions"]
