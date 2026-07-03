"""Persistent vessel state: location, notes, and calendar commitments."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = APP_ROOT / "data" / "vessel" / "state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _blank_state() -> Dict[str, Any]:
    return {
        "schema_version": "vessel_state.v1",
        "updated_at": _now(),
        "location": None,
        "location_history": [],
        "notes": [],
        "calendar_events": [],
    }


def _state_path(data_dir: Optional[Path] = None) -> Path:
    if data_dir is None:
        return DEFAULT_STATE_PATH
    return Path(data_dir) / "vessel" / "state.json"


def load_state(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    path = _state_path(data_dir)
    if not path.exists():
        return _blank_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    state = _blank_state()
    if isinstance(data, dict):
        state.update({k: v for k, v in data.items() if k in state})
    if not isinstance(state.get("location_history"), list):
        state["location_history"] = []
    if not isinstance(state.get("notes"), list):
        state["notes"] = []
    if not isinstance(state.get("calendar_events"), list):
        state["calendar_events"] = []
    return state


def save_state(state: Dict[str, Any], data_dir: Optional[Path] = None) -> Dict[str, Any]:
    state = dict(state or {})
    state.setdefault("schema_version", "vessel_state.v1")
    state["updated_at"] = _now()
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def set_location(
    *,
    lat: float,
    lon: float,
    label: str = "",
    source: str = "manual",
    confidence: float = 1.0,
    note: str = "",
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    lat = float(lat)
    lon = float(lon)
    if not (-90 <= lat <= 90):
        raise ValueError("lat must be between -90 and 90")
    if not (-180 <= lon <= 180):
        raise ValueError("lon must be between -180 and 180")
    confidence = max(0.0, min(float(confidence), 1.0))
    location = {
        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "label": str(label or "").strip()[:160],
        "source": str(source or "manual").strip()[:80],
        "confidence": confidence,
        "note": str(note or "").strip()[:500],
        "updated_at": _now(),
    }
    state = load_state(data_dir)
    state["location"] = location
    history = [location] + list(state.get("location_history") or [])
    state["location_history"] = history[:50]
    return save_state(state, data_dir)


def add_note(
    *,
    title: str,
    body: str = "",
    kind: str = "system_note",
    source: str = "manual",
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    title = str(title or "").strip()
    body = str(body or "").strip()
    if not title and body:
        title = body.splitlines()[0][:80]
    if not title:
        raise ValueError("note title or body is required")
    now = _now()
    note = {
        "id": "note_" + uuid.uuid4().hex[:12],
        "title": title[:160],
        "body": body[:5000],
        "kind": str(kind or "system_note").strip()[:80],
        "source": str(source or "manual").strip()[:80],
        "created_at": now,
        "updated_at": now,
    }
    state = load_state(data_dir)
    state["notes"] = [note] + list(state.get("notes") or [])
    state["notes"] = state["notes"][:200]
    return save_state(state, data_dir)


def delete_note(note_id: str, data_dir: Optional[Path] = None) -> Dict[str, Any]:
    state = load_state(data_dir)
    before = len(state.get("notes") or [])
    state["notes"] = [n for n in state.get("notes") or [] if n.get("id") != note_id]
    if len(state["notes"]) == before:
        raise KeyError(note_id)
    return save_state(state, data_dir)


def add_calendar_event(
    *,
    title: str,
    start: str,
    end: str = "",
    location: str = "",
    description: str = "",
    source: str = "manual",
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    title = str(title or "").strip()
    start = str(start or "").strip()
    if not title:
        raise ValueError("calendar event title is required")
    if not start:
        raise ValueError("calendar event start is required")
    now = _now()
    event = {
        "id": "evt_" + uuid.uuid4().hex[:12],
        "title": title[:180],
        "start": start[:40],
        "end": str(end or "").strip()[:40],
        "location": str(location or "").strip()[:200],
        "description": str(description or "").strip()[:1000],
        "source": str(source or "manual").strip()[:80],
        "status": "scheduled",
        "created_at": now,
        "updated_at": now,
    }
    state = load_state(data_dir)
    events = [event] + list(state.get("calendar_events") or [])
    events.sort(key=lambda e: e.get("start") or "9999")
    state["calendar_events"] = events[:300]
    return save_state(state, data_dir)


def list_calendar_events(
    *,
    from_dt: str = "",
    to_dt: str = "",
    limit: int = 50,
    data_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    state = load_state(data_dir)
    events = list(state.get("calendar_events") or [])
    if from_dt:
        events = [e for e in events if str(e.get("start") or "")[:10] >= from_dt]
    if to_dt:
        events = [e for e in events if str(e.get("start") or "")[:10] <= to_dt]
    events.sort(key=lambda e: e.get("start") or "9999")
    return events[: max(1, min(int(limit or 50), 200))]


def context_summary(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    state = load_state(data_dir)
    notes = list(state.get("notes") or [])
    events = list(state.get("calendar_events") or [])
    events.sort(key=lambda e: e.get("start") or "9999")
    return {
        "location": state.get("location"),
        "recent_notes": [
            {
                "title": n.get("title"),
                "kind": n.get("kind"),
                "source": n.get("source"),
                "updated_at": n.get("updated_at"),
            }
            for n in notes[:5]
        ],
        "upcoming_events": [
            {
                "title": e.get("title"),
                "start": e.get("start"),
                "location": e.get("location"),
            }
            for e in events[:5]
        ],
    }
