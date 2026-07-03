"""Upgrade snapshot manifests for self-upgrade rollback auditing."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_SCHEMA = "upgrade_snapshot.v1"

DEFAULT_TRACKED_PATHS = (
    "app.py",
    "upgrade_engine.py",
    "config",
    "data/benchmarks",
    "services/cost_aware_router.py",
    "services/kairos_memory.py",
    "services/protocol_concepts.py",
    "services/runtime_identity.py",
    "services/stability_golden.py",
    "services/upgrade_report.py",
    "services/world_simulator.py",
    "services/custom_tools",
    "static/app.js",
    "static/index.html",
    "static/style_v2.css",
    "tools/benchmark_runner.py",
    "tools/encoding_audit.py",
    "tools/prompt_regression_check.py",
    "tools/stability_golden_runner.py",
    "tools/system_stability_check.py",
)

_SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git", "node_modules"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(resolved)


def _resolve_path(path_text: str, root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return root / path


def _should_include(path: Path) -> bool:
    if any(part in _SKIP_PARTS for part in path.parts):
        return False
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return False
    return path.is_file()


def _iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        if _should_include(path):
            yield path
        return
    if not path.exists():
        return
    for item in sorted(path.rglob("*")):
        if _should_include(item):
            yield item


def _file_entry(path: Path, root: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "path": _display_path(path, root),
            "exists": False,
        }
    stat = path.stat()
    return {
        "path": _display_path(path, root),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256_file(path),
    }


def _aggregate(entries: Iterable[Dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.get("path", "")):
        digest.update(str(entry.get("path", "")).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry.get("exists", False)).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(entry.get("sha256", "")).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _tracked_roots(
    *,
    root: Path,
    tracked_paths: Optional[Iterable[str | Path]] = None,
    extra_paths: Optional[Iterable[str | Path]] = None,
) -> List[Path]:
    raw = list(tracked_paths or DEFAULT_TRACKED_PATHS) + list(extra_paths or [])
    result: List[Path] = []
    seen = set()
    for item in raw:
        path = Path(item)
        if not path.is_absolute():
            path = root / path
        resolved = path.resolve()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def build_upgrade_snapshot(
    *,
    plan_id: str,
    label: str = "pre_install",
    root: Path = ROOT,
    tracked_paths: Optional[Iterable[str | Path]] = None,
    extra_paths: Optional[Iterable[str | Path]] = None,
) -> Dict[str, Any]:
    root = Path(root)
    roots = _tracked_roots(root=root, tracked_paths=tracked_paths, extra_paths=extra_paths)
    entries: List[Dict[str, Any]] = []
    for base in roots:
        if not base.exists():
            entries.append(_file_entry(base, root))
            continue
        entries.extend(_file_entry(path, root) for path in _iter_files(base))

    entries = sorted(entries, key=lambda item: item.get("path", ""))
    return {
        "schema_version": SNAPSHOT_SCHEMA,
        "plan_id": plan_id,
        "label": label,
        "created_at": _now(),
        "root": str(root.resolve()),
        "tracked_roots": [_display_path(path, root) for path in roots],
        "file_count": len([entry for entry in entries if entry.get("exists")]),
        "missing_count": len([entry for entry in entries if not entry.get("exists")]),
        "aggregate_sha256": _aggregate(entries),
        "files": entries,
    }


def write_upgrade_snapshot(snapshot: Dict[str, Any], *, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_id = str(snapshot.get("plan_id") or "unknown").replace("/", "_").replace("\\", "_")
    label = str(snapshot.get("label") or "snapshot").replace("/", "_").replace("\\", "_")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"{plan_id}_{label}_{stamp}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def create_upgrade_snapshot(
    *,
    plan_id: str,
    label: str = "pre_install",
    root: Path = ROOT,
    output_dir: Optional[Path] = None,
    tracked_paths: Optional[Iterable[str | Path]] = None,
    extra_paths: Optional[Iterable[str | Path]] = None,
) -> Dict[str, Any]:
    snapshot = build_upgrade_snapshot(
        plan_id=plan_id,
        label=label,
        root=root,
        tracked_paths=tracked_paths,
        extra_paths=extra_paths,
    )
    if output_dir is not None:
        path = write_upgrade_snapshot(snapshot, output_dir=Path(output_dir))
        snapshot["path"] = str(path)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def load_upgrade_snapshot(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def diff_upgrade_snapshot(snapshot: Dict[str, Any], *, root: Optional[Path] = None) -> Dict[str, Any]:
    root_path = Path(root or snapshot.get("root") or ROOT)
    tracked = snapshot.get("tracked_roots") or []
    current = build_upgrade_snapshot(
        plan_id=str(snapshot.get("plan_id") or "diff"),
        label="current",
        root=root_path,
        tracked_paths=[_resolve_path(path, root_path) for path in tracked],
    )
    before = {entry.get("path"): entry for entry in snapshot.get("files") or []}
    after = {entry.get("path"): entry for entry in current.get("files") or []}

    added = sorted(path for path in after if path not in before and after[path].get("exists"))
    removed = sorted(path for path in before if path not in after or not after[path].get("exists"))
    changed = sorted(
        path
        for path in before.keys() & after.keys()
        if before[path].get("sha256") != after[path].get("sha256")
        or before[path].get("exists") != after[path].get("exists")
    )
    unchanged = sorted(
        path
        for path in before.keys() & after.keys()
        if path not in changed
    )
    clean = not changed and not added and not removed
    return {
        "schema_version": "upgrade_snapshot_diff.v1",
        "plan_id": snapshot.get("plan_id"),
        "snapshot_label": snapshot.get("label"),
        "snapshot_path": snapshot.get("path"),
        "before_aggregate_sha256": snapshot.get("aggregate_sha256"),
        "after_aggregate_sha256": current.get("aggregate_sha256"),
        "changed": changed,
        "added": added,
        "removed": removed,
        "changed_count": len(changed),
        "added_count": len(added),
        "removed_count": len(removed),
        "unchanged_count": len(unchanged),
        "clean": clean,
    }
