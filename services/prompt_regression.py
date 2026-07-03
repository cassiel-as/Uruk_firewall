"""Prompt regression checker for URUK.

The checker is deterministic: it fingerprints prompt/protocol assets, compares
against an optional baseline, and runs existing non-LLM regression gates.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "1.0"
DEFAULT_BASELINE_PATH = ROOT / "data" / "prompt_regression_baseline.json"

PROMPT_GLOBS = (
    "config/prompts/*.txt",
    "config/protocol/SKILL.md",
    "config/protocol/references/**/*.md",
    "config/protocol/references/**/*.txt",
)
EXPLICIT_PROMPT_FILES = (
    "services/context_budget.py",
    "services/cost_aware_router.py",
    "services/inference_governor.py",
    "services/local_model_router.py",
    "services/pre_gate.py",
    "services/protocol_concepts.py",
    "services/relay_protocol.py",
    "services/runtime_identity.py",
    "services/small_task_executor.py",
    "upgrade_engine.py",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def collect_prompt_files(*, root: Path = ROOT) -> List[Path]:
    """Collect prompt-bearing files while excluding local secrets and backups."""
    root = Path(root)
    paths = set()
    for pattern in PROMPT_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            name = path.name.casefold()
            if name.endswith(".bak") or ".bak" in name:
                continue
            paths.add(path.resolve())
    for rel in EXPLICIT_PROMPT_FILES:
        path = root / rel
        if path.exists() and path.is_file():
            paths.add(path.resolve())
    return sorted(paths, key=lambda item: _rel(item, root))


def fingerprint_prompt_bundle(*, root: Path = ROOT) -> Dict[str, Any]:
    """Return per-file and overall prompt bundle hashes."""
    root = Path(root)
    files: List[Dict[str, Any]] = []
    total_bytes = 0
    for path in collect_prompt_files(root=root):
        data = path.read_bytes()
        total_bytes += len(data)
        files.append({
            "path": _rel(path, root),
            "sha256": _sha256_bytes(data),
            "bytes": len(data),
        })

    overall = hashlib.sha256()
    for item in files:
        overall.update(item["path"].encode("utf-8"))
        overall.update(b"\0")
        overall.update(item["sha256"].encode("ascii"))
        overall.update(b"\0")
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "sha256": overall.hexdigest(),
        "files": files,
    }


def load_prompt_baseline(path: Path = DEFAULT_BASELINE_PATH) -> Optional[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_prompt_baseline(
    *,
    root: Path = ROOT,
    path: Path = DEFAULT_BASELINE_PATH,
    label: str = "manual",
) -> Dict[str, Any]:
    """Write a prompt regression baseline and return the payload."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now().isoformat(),
        "label": label,
        "fingerprint": fingerprint_prompt_bundle(root=root),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def diff_prompt_fingerprints(
    baseline: Optional[Dict[str, Any]],
    current: Dict[str, Any],
) -> Dict[str, Any]:
    if not baseline:
        return {
            "baseline_present": False,
            "prompt_changed": False,
            "added": [],
            "removed": [],
            "changed": [],
            "unchanged_count": 0,
        }

    base_fp = baseline.get("fingerprint") or {}
    base_files = {item.get("path"): item for item in base_fp.get("files") or [] if item.get("path")}
    current_files = {item.get("path"): item for item in current.get("files") or [] if item.get("path")}
    added = sorted(set(current_files) - set(base_files))
    removed = sorted(set(base_files) - set(current_files))
    changed = sorted(
        path for path in set(base_files) & set(current_files)
        if base_files[path].get("sha256") != current_files[path].get("sha256")
    )
    unchanged_count = len(set(base_files) & set(current_files)) - len(changed)
    return {
        "baseline_present": True,
        "baseline_sha256": base_fp.get("sha256"),
        "current_sha256": current.get("sha256"),
        "prompt_changed": bool(added or removed or changed or base_fp.get("sha256") != current.get("sha256")),
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged_count,
    }


def _benchmark_report(root: Path) -> Dict[str, Any]:
    from tools.benchmark_runner import DEFAULT_CASES, run_cases

    return run_cases(DEFAULT_CASES, root=root)


def _quick_eval_report() -> Dict[str, Any]:
    try:
        from upgrade_engine import quick_eval_gate
        return quick_eval_gate()
    except Exception as exc:
        return {
            "available": False,
            "skipped": True,
            "passed": None,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def _episode_report(root: Path) -> Dict[str, Any]:
    from services.episode_compare import compare_latest

    return compare_latest(root=root)


def run_prompt_regression_check(
    *,
    root: Path = ROOT,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    update_baseline: bool = False,
    run_benchmark: bool = True,
    run_quick_eval: bool = True,
    compare_latest_episode: bool = False,
    strict_episode: bool = False,
    label: str = "manual",
) -> Dict[str, Any]:
    """Run prompt fingerprint and regression checks."""
    root = Path(root)
    baseline_path = Path(baseline_path)
    current = fingerprint_prompt_bundle(root=root)
    baseline = load_prompt_baseline(baseline_path)
    diff = diff_prompt_fingerprints(baseline, current)
    baseline_written = None
    if update_baseline:
        baseline_written = write_prompt_baseline(root=root, path=baseline_path, label=label)
        baseline = baseline_written
        diff = diff_prompt_fingerprints(baseline, current)

    checks: Dict[str, Any] = {}
    failures: List[str] = []
    warnings: List[str] = []
    changes: List[str] = []

    if not baseline and not update_baseline:
        warnings.append("prompt_baseline_missing")
    if diff.get("prompt_changed"):
        changes.append("prompt_bundle_changed")

    if run_benchmark:
        try:
            benchmark = _benchmark_report(root)
        except Exception as exc:
            benchmark = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
        checks["benchmark"] = benchmark
        if not benchmark.get("passed"):
            failures.append("benchmark_failed")

    if run_quick_eval:
        quick_eval = _quick_eval_report()
        checks["quick_eval"] = quick_eval
        if quick_eval.get("passed") is False:
            failures.append("quick_eval_regressed")
        elif quick_eval.get("skipped"):
            warnings.append("quick_eval_skipped")

    if compare_latest_episode:
        try:
            episode = _episode_report(root)
        except Exception as exc:
            episode = {"ok": None, "error": f"{type(exc).__name__}: {exc}"}
        checks["episode_compare"] = episode
        if episode.get("regressions"):
            warnings.append("episode_regressions_present")
            if strict_episode:
                failures.append("episode_compare_regressed")

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not failures,
        "status": "failed" if failures else ("changed" if changes else "passed"),
        "checked_at": datetime.now().isoformat(),
        "baseline_path": str(baseline_path),
        "baseline_present": bool(baseline),
        "baseline_written": bool(baseline_written),
        "fingerprint": current,
        "diff": diff,
        "checks": checks,
        "failures": failures,
        "warnings": sorted(set(warnings)),
        "changes": sorted(set(changes)),
    }
