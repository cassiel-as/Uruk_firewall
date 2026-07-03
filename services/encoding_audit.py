"""Content encoding and mojibake audit helpers for URUK.

The goal is detection, not blind repair. Some old runtime artifacts can carry
double-decoded text where UTF-8 bytes were interpreted as latin-1/cp1252-like
text. This module identifies those files so repairs can stay scoped and
reviewable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


ROOT = Path(__file__).parent.parent

TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".py"}
DEFAULT_EXCLUDED_PREFIXES = (
    ".git/",
    ".mypy_cache/",
    ".pytest_cache/",
    "__pycache__/",
    "data/rag_index/",
    # 第三方虛擬環境 + ML 訓練產物：唔屬本專案內容。第三方庫嘅測試 fixture
    # 同 model tokenizer 嘅 byte-level BPE token 會誤觸 mojibake heuristic，
    # 令 audit 對住唔關事嘅檔報 issue（宣告 audit scope 邊界）。
    ".venv/",
    ".venv-training/",
    "venv/",
    "node_modules/",
    "training/artifacts/",
)

MOJIBAKE_MARKERS = (
    "\ufffd",
    "\u00c3",
    "\u00c2",
    "\u00e2\u20ac",
    "\u00e2\x80",
    "\u00e2\x9c",
    "\u00e5\x8d",
    "\u00e7\u00b4",
    "\u00e6\x88",
    "\u00e3\x80",
    "\u00ef\u00bc",
)

_PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
_C1_CONTROL_RE = re.compile(r"[\u0080-\u009f]")


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _sample(text: str, index: int, *, radius: int = 80) -> str:
    start = max(0, index - radius)
    end = min(len(text), index + radius)
    return text[start:end].replace("\r", "\\r").replace("\n", "\\n")


def _marker_hits(text: str) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for marker in MOJIBAKE_MARKERS:
        index = text.find(marker)
        if index < 0:
            continue
        hits.append({
            "marker": marker.encode("unicode_escape").decode("ascii"),
            "count": text.count(marker),
            "sample": _sample(text, index),
        })
    return hits


def _first_regex_hit(pattern: re.Pattern[str], text: str) -> Optional[Dict[str, Any]]:
    match = pattern.search(text)
    if not match:
        return None
    return {
        "codepoint": f"U+{ord(match.group(0)):04X}",
        "sample": _sample(text, match.start()),
    }


def _can_latin1_utf8_repair(text: str) -> bool:
    """Return true when text can be round-tripped as latin-1 bytes to UTF-8.

    This is a common repair for strings that were UTF-8 bytes incorrectly
    decoded as latin-1/cp1252-like text. It is only a signal; callers should
    still review output before writing.
    """
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return False
    return repaired != text


def analyze_text(text: str) -> Dict[str, Any]:
    replacement_count = text.count("\ufffd")
    private_use_count = len(_PRIVATE_USE_RE.findall(text))
    c1_count = len(_C1_CONTROL_RE.findall(text))
    marker_hits = _marker_hits(text)

    issues: List[Dict[str, Any]] = []
    if replacement_count:
        issues.append({"code": "replacement_char", "severity": "P1", "count": replacement_count})
    if c1_count:
        hit = _first_regex_hit(_C1_CONTROL_RE, text)
        issues.append({
            "code": "c1_control_chars",
            "severity": "P1",
            "count": c1_count,
            "sample": hit,
        })
    if private_use_count:
        hit = _first_regex_hit(_PRIVATE_USE_RE, text)
        issues.append({
            "code": "private_use_chars",
            "severity": "P2",
            "count": private_use_count,
            "sample": hit,
        })
    if marker_hits:
        issues.append({
            "code": "mojibake_markers",
            "severity": "P2",
            "count": sum(hit["count"] for hit in marker_hits),
            "markers": marker_hits[:5],
        })

    return {
        "replacement_count": replacement_count,
        "private_use_count": private_use_count,
        "c1_control_count": c1_count,
        "marker_hits": marker_hits,
        "latin1_utf8_repair_possible": _can_latin1_utf8_repair(text),
        "issues": issues,
    }


def iter_text_files(
    root: Path = ROOT,
    *,
    suffixes: Iterable[str] = TEXT_SUFFIXES,
    excluded_prefixes: Sequence[str] = DEFAULT_EXCLUDED_PREFIXES,
) -> List[Path]:
    root = Path(root)
    suffix_set = {suffix.casefold() for suffix in suffixes}
    out: List[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in suffix_set:
            continue
        rel = _rel(path, root)
        if any(rel.startswith(prefix) for prefix in excluded_prefixes):
            continue
        out.append(path)
    return sorted(out, key=lambda p: _rel(p, root))


def audit_encoding(
    root: Path = ROOT,
    *,
    paths: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    root = Path(root)
    scan_paths = list(paths) if paths is not None else iter_text_files(root)
    files: List[Dict[str, Any]] = []
    issue_counts: Dict[str, int] = {}
    for path in scan_paths:
        path = Path(path)
        rel = _rel(path, root)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception as exc:
            item = {
                "path": rel,
                "issues": [{
                    "code": "read_error",
                    "severity": "P1",
                    "message": f"{type(exc).__name__}: {exc}",
                }],
            }
        else:
            item = {"path": rel, **analyze_text(text)}
        if item.get("issues"):
            files.append(item)
            for issue in item["issues"]:
                code = str(issue.get("code") or "unknown")
                issue_counts[code] = issue_counts.get(code, 0) + 1

    return {
        "schema_version": "1.0",
        "file_count": len(scan_paths),
        "flagged_count": len(files),
        "clean": not files,
        "issue_counts": issue_counts,
        "files": files,
    }


def format_summary(report: Dict[str, Any]) -> str:
    lines = [
        "URUK encoding audit",
        f"  files: {report.get('file_count', 0)}",
        f"  flagged: {report.get('flagged_count', 0)}",
        f"  clean: {report.get('clean')}",
    ]
    issue_counts = report.get("issue_counts") or {}
    if issue_counts:
        joined = ", ".join(f"{key}={value}" for key, value in sorted(issue_counts.items()))
        lines.append(f"  issues: {joined}")
    for item in (report.get("files") or [])[:12]:
        codes = ", ".join(str(issue.get("code")) for issue in item.get("issues") or [])
        repair = " repair=latin1->utf8" if item.get("latin1_utf8_repair_possible") else ""
        lines.append(f"  - {item.get('path')}: {codes}{repair}")
    return "\n".join(lines)


def to_json(report: Dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
