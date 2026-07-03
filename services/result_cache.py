"""Small deterministic result cache for low-cost routes."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


CACHE_REL = Path("data/cache/result_cache.json")
SCHEMA_VERSION = "1.0"
MAX_ENTRIES = 200


def cache_key(*parts: Any) -> str:
    raw = "\0".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def get_cached_result(root: Path, key: str, *, max_age_seconds: int | None = None) -> dict[str, Any] | None:
    payload = _load(root)
    item = (payload.get("entries") or {}).get(str(key))
    if not isinstance(item, dict):
        return None
    if max_age_seconds is not None:
        created = float(item.get("created_at_epoch") or 0)
        if created and (time.time() - created) > max_age_seconds:
            return None
    item["cache_hit"] = True
    return item


def set_cached_result(root: Path, key: str, value: dict[str, Any]) -> dict[str, Any]:
    payload = _load(root)
    entries = payload.setdefault("entries", {})
    entries[str(key)] = {
        "created_at_epoch": time.time(),
        "value": value,
    }
    _trim(entries)
    _write(root, payload)
    return entries[str(key)]


def _load(root: Path) -> dict[str, Any]:
    path = Path(root) / CACHE_REL
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    if not isinstance(payload, dict):
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("entries", {})
    if not isinstance(payload["entries"], dict):
        payload["entries"] = {}
    return payload


def _write(root: Path, payload: dict[str, Any]) -> None:
    path = Path(root) / CACHE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _trim(entries: dict[str, Any]) -> None:
    if len(entries) <= MAX_ENTRIES:
        return
    ranked = sorted(
        entries.items(),
        key=lambda item: float((item[1] or {}).get("created_at_epoch") or 0),
    )
    for key, _ in ranked[: max(0, len(entries) - MAX_ENTRIES)]:
        entries.pop(key, None)
