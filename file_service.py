"""
URUK Trinity Console — File Service

3-tier file access for the customization UI (FT-1).

Layer 1 (canonical, read-only):
    data/core/*.md      — KAIROS_CORE / PHYSICS_CONSTANTS
    data/protocol/*.md  — protocol canonical docs

Layer 2 (auditable, writable with audit log + backup):
    config/prompts/*.txt   — Stage prompts (dispatcher / father / son / spirit / council / delabeling / explanation / filter)
    config/nodes.yaml      — LLM node configuration (single file)

Layer 3 (personal, writable with backup):
    data/kairos/*       — Kairos memory docs/proposals (raw sessions live in conversation_history)
    data/experiments/*  — Experiment files
    data/causal_db/*    — Personal CAU entries

Security:
    - Path traversal rejected (Path.resolve + is_relative_to BASE_DIR)
    - Symlink escape rejected
    - Hard 1 MB write size limit
    - UTF-8 mandatory (operator on Windows cp950)
"""

import hashlib
import json
import difflib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


BASE_DIR = Path(__file__).parent.resolve()
HISTORY_DIR = BASE_DIR / ".uruk-history"
AUDIT_LOG_DIR = BASE_DIR / "data" / "audit_log"

MAX_WRITE_BYTES = 1_048_576  # 1 MB

# 4-tier whitelist. Each value is a list of allowed roots relative to BASE_DIR.
# A root may be a directory (all .md/.txt/.yaml children) or a specific file.
LAYER_ROOTS: Dict[str, List[str]] = {
    "canonical": [
        "data/core",
        "data/protocol",
        "data/theory",
        "data/misc",
        "data/causal_records",
        "config/protocol/references/module_t",
    ],
    "prompts":   ["config/prompts"],
    "personal":  ["data/kairos", "data/experiments", "data/causal_db"],
    "config":    ["config/nodes.yaml", "config/.env"],  # single-file roots (v8.36)
}

# Which layers are read-only
READ_ONLY_LAYERS = {"canonical"}

# Layers that require audit log on write
AUDITED_LAYERS = {"prompts", "config"}


@dataclass
class FileInfo:
    path: str            # relative to BASE_DIR, posix style
    layer: str           # canonical / prompts / personal / config
    readonly: bool
    size: int
    mtime: str           # ISO-8601
    sha256: str

    def to_dict(self) -> Dict:
        return {
            "path": self.path,
            "layer": self.layer,
            "readonly": self.readonly,
            "size": self.size,
            "mtime": self.mtime,
            "sha256": self.sha256,
        }


class FileServiceError(Exception):
    """Generic file service error."""


class PathRejected(FileServiceError):
    """Path failed safety validation."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _detect_layer(resolved: Path) -> Optional[Tuple[str, str]]:
    """Return (layer, root_rel) if resolved path is within any whitelisted root,
    else None."""
    try:
        rel = resolved.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return None
    for layer, roots in LAYER_ROOTS.items():
        for root_rel in roots:
            root_abs = (BASE_DIR / root_rel).resolve()
            if root_abs == resolved:
                # Single-file root exact match
                return (layer, root_rel)
            try:
                resolved.relative_to(root_abs)
                # If we reach here, resolved is inside root_abs
                if root_abs.is_dir():
                    return (layer, root_rel)
            except ValueError:
                continue
    return None


def _resolve_safe(rel_path: str) -> Tuple[Path, str]:
    """Validate + resolve a relative path. Returns (absolute_path, layer).

    Raises PathRejected if path is outside whitelisted roots, contains ..,
    is absolute, or escapes via symlink.
    """
    if not rel_path or not isinstance(rel_path, str):
        raise PathRejected("path must be non-empty string")
    # Normalize slashes
    rel_path = rel_path.replace("\\", "/").strip("/")
    if not rel_path:
        raise PathRejected("path empty after normalization")
    # Reject absolute paths
    if Path(rel_path).is_absolute():
        raise PathRejected(f"absolute paths rejected: {rel_path!r}")
    # Reject .. parts explicitly (even though resolve() would catch most)
    parts = Path(rel_path).parts
    if any(p == ".." for p in parts):
        raise PathRejected(f"parent-dir reference rejected: {rel_path!r}")

    candidate = (BASE_DIR / rel_path).resolve()

    # Must stay inside BASE_DIR
    try:
        candidate.relative_to(BASE_DIR)
    except ValueError:
        raise PathRejected(f"path escapes base dir: {rel_path!r}")

    # Must fall under a whitelisted layer root
    layer_info = _detect_layer(candidate)
    if layer_info is None:
        raise PathRejected(f"path outside whitelist: {rel_path!r}")

    return candidate, layer_info[0]


# ─────────────────────────────────────────────────────────────────
class FileService:
    """File operations for FT-1 UI. Use module-level singleton fs."""

    # ─── Tree ───
    def get_tree(self) -> Dict:
        """Return 4-tier tree of all whitelisted files.

        Returns:
            {
              "canonical": {"files": [FileInfo.to_dict, ...], "roots": [...]},
              "prompts":   {...},
              "personal":  {...},
              "config":    {...}
            }
        """
        tree = {}
        for layer, roots in LAYER_ROOTS.items():
            files: List[FileInfo] = []
            for root_rel in roots:
                root_abs = (BASE_DIR / root_rel).resolve()
                if not root_abs.exists():
                    continue
                if root_abs.is_file():
                    files.append(self._stat_info(root_abs, layer))
                else:
                    # Iterate directory tree
                    for p in sorted(root_abs.rglob("*")):
                        if p.is_file() and not p.name.startswith("."):
                            # Only include common text-like files
                            if p.suffix.lower() in (".md", ".txt", ".yaml", ".yml", ".py", ".json"):
                                files.append(self._stat_info(p, layer))
            tree[layer] = {
                "roots": roots,
                "readonly": layer in READ_ONLY_LAYERS,
                "audited": layer in AUDITED_LAYERS,
                "files": [f.to_dict() for f in files],
            }
        return tree

    def _stat_info(self, abs_path: Path, layer: str) -> FileInfo:
        stat = abs_path.stat()
        try:
            data = abs_path.read_bytes()
        except (PermissionError, OSError):
            data = b""
        rel = abs_path.resolve().relative_to(BASE_DIR).as_posix()
        return FileInfo(
            path=rel,
            layer=layer,
            readonly=(layer in READ_ONLY_LAYERS),
            size=stat.st_size,
            mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            sha256=_sha256(data),
        )

    # ─── Read ───
    def read_file(self, rel_path: str) -> Dict:
        abs_path, layer = _resolve_safe(rel_path)
        if not abs_path.exists():
            raise FileNotFoundError(rel_path)
        if not abs_path.is_file():
            raise FileServiceError(f"not a file: {rel_path}")
        try:
            content = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise FileServiceError(f"non-UTF-8 file: {e}")
        info = self._stat_info(abs_path, layer)
        result = info.to_dict()
        result["content"] = content
        return result

    # ─── Write ───
    def write_file(self, rel_path: str, content: str) -> Dict:
        if not isinstance(content, str):
            raise ValueError("content must be string")
        # Size guard
        size = len(content.encode("utf-8"))
        if size > MAX_WRITE_BYTES:
            raise ValueError(f"content exceeds {MAX_WRITE_BYTES} bytes (got {size})")

        abs_path, layer = _resolve_safe(rel_path)

        if layer in READ_ONLY_LAYERS:
            raise PermissionError(f"layer '{layer}' is read-only: {rel_path}")

        # Backup existing file (if any) before write
        backup_info = None
        if abs_path.exists():
            backup_info = self._backup(abs_path, rel_path)

        # Ensure parent dir exists
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")

        # Audit log for layers requiring it
        if layer in AUDITED_LAYERS:
            self._audit_log({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "action": "write",
                "path": rel_path,
                "layer": layer,
                "size": size,
                "sha256_new": _sha256(content.encode("utf-8")),
                "sha256_backup": backup_info.get("sha256") if backup_info else None,
                "backup_path": backup_info.get("backup_path") if backup_info else None,
            })

        info = self._stat_info(abs_path, layer)
        out = info.to_dict()
        out["backup"] = backup_info
        return out

    def _backup(self, abs_path: Path, rel_path: str) -> Dict:
        """Copy current content to .uruk-history/<rel_path>.<unix_ts>."""
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(datetime.now().timestamp())
        backup_rel = f"{rel_path}.{ts}"
        backup_abs = HISTORY_DIR / backup_rel
        backup_abs.parent.mkdir(parents=True, exist_ok=True)
        data = abs_path.read_bytes()
        backup_abs.write_bytes(data)
        return {
            "backup_path": str(backup_abs.resolve().relative_to(BASE_DIR).as_posix()),
            "sha256": _sha256(data),
            "ts": ts,
        }

    def _audit_log(self, entry: Dict):
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_path = AUDIT_LOG_DIR / f"file_writes_{date_str}.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ─── Diff ───
    def diff_file(self, rel_path: str, version: Optional[str] = None) -> Dict:
        """Diff current vs most-recent backup snapshot (or specified version)."""
        abs_path, layer = _resolve_safe(rel_path)
        if not abs_path.exists():
            raise FileNotFoundError(rel_path)
        current = abs_path.read_text(encoding="utf-8")

        # Find backup
        backup_glob = f"{rel_path}.*"
        # Resolve potential backup path safely (still inside HISTORY_DIR)
        history_for_path = HISTORY_DIR / Path(rel_path).parent
        if not history_for_path.exists():
            return {
                "path": rel_path,
                "current_size": len(current),
                "has_backup": False,
                "diff": "",
            }
        candidates = sorted(
            history_for_path.glob(f"{Path(rel_path).name}.*"),
            key=lambda p: p.name,
            reverse=True,
        )
        if version:
            # specific ts
            candidates = [c for c in candidates if c.name.endswith(f".{version}")]
        if not candidates:
            return {
                "path": rel_path,
                "current_size": len(current),
                "has_backup": False,
                "diff": "",
            }
        backup_path = candidates[0]
        prev = backup_path.read_text(encoding="utf-8")
        diff = "\n".join(difflib.unified_diff(
            prev.splitlines(),
            current.splitlines(),
            fromfile=f"{rel_path}@{backup_path.name.rsplit('.', 1)[-1]}",
            tofile=f"{rel_path}@current",
            lineterm="",
        ))
        return {
            "path": rel_path,
            "layer": layer,
            "has_backup": True,
            "backup_name": backup_path.name,
            "diff": diff,
        }


# Module-level singleton
fs = FileService()
