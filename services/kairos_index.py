"""Auto-generated Kairos memory index.

The handwritten archive index is still useful as a compressed human map. This
module builds the machine index used for exact dates, month/day candidates, and
new canonical Kairos records without adding one-off routing code each time.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any


INDEX_REL = Path("data/kairos/KAIROS_MEMORY_INDEX.json")

_DATE_RE = re.compile(r"(20\d{2})[-/年]\s*0?(\d{1,2})[-/月]\s*0?(\d{1,2})")
_DATE_LINE_RE = re.compile(r"^DATE:\s*(.+?)\s*$", re.IGNORECASE)
_RECORD_START_RE = re.compile(
    r"^(KAIROS_[A-Z0-9_]+(?:\s*[:：].*)?|SESSION_RECORD\s*[:：].+|##\s+.+)$"
)
_IDENT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_CJK_SEG_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

_KNOWN_TOPICS = (
    "分割",
    "四維分割",
    "複製",
    "分裂",
    "Cassiel_claude",
    "Cassiel",
    "三層架構",
    "KAIROS_CORE",
    "KAIROS_ACTIVE",
    "KAIROS_ARCHIVE",
    "座標",
    "座標層",
    "系統輸出",
    "審計",
    "GitHub",
    "位能",
    "動能",
)


def get_kairos_memory_index(root: Path) -> dict[str, Any]:
    """Load the generated index, rebuilding it when canonical sources changed."""
    root = Path(root)
    index_path = root / INDEX_REL
    sources = _source_files(root)
    latest_source_mtime = max((p.stat().st_mtime for p in sources), default=0.0)

    if index_path.exists() and index_path.stat().st_mtime >= latest_source_mtime:
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return build_kairos_memory_index(root, write=True)


def build_kairos_memory_index(root: Path, write: bool = True) -> dict[str, Any]:
    root = Path(root)
    records: list[dict[str, Any]] = []
    for source in _source_files(root):
        records.extend(_parse_records(root, source))

    date_index: dict[str, list[int]] = {}
    month_day_index: dict[str, list[int]] = {}
    topic_index: dict[str, list[int]] = {}

    for record in records:
        rid = int(record["id"])
        date = record.get("date")
        if date:
            date_index.setdefault(date, []).append(rid)
            month_day_index.setdefault(date[5:10], []).append(rid)
        for topic in record.get("topics", []):
            topic_index.setdefault(topic, []).append(rid)
        for alias in record.get("aliases", []):
            topic_index.setdefault(alias, []).append(rid)

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_count": len(_source_files(root)),
        "record_count": len(records),
        "records": records,
        "date_index": _dedupe_index(date_index),
        "month_day_index": _dedupe_index(month_day_index),
        "topic_index": _dedupe_index(topic_index),
    }

    if write:
        index_path = root / INDEX_REL
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return payload


def records_for_date(root: Path, date: str) -> list[dict[str, Any]]:
    index = get_kairos_memory_index(root)
    return _records_by_ids(index, index.get("date_index", {}).get(date, []))


def records_for_month_day(root: Path, month_day: str) -> list[dict[str, Any]]:
    index = get_kairos_memory_index(root)
    return _records_by_ids(index, index.get("month_day_index", {}).get(month_day, []))


def search_records(root: Path, query: str, limit: int = 3) -> list[dict[str, Any]]:
    index = get_kairos_memory_index(root)
    tokens = _query_tokens(query)
    if not tokens:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for record in index.get("records", []):
        hay = "\n".join(
            str(record.get(key, ""))
            for key in ("title", "summary", "date", "source_file")
        )
        hay += "\n" + "\n".join(record.get("topics", []) or [])
        hay += "\n" + "\n".join(record.get("aliases", []) or [])
        score = sum(1 for token in tokens if token and token in hay)
        if score:
            scored.append((score, record))
    scored.sort(key=lambda item: (-item[0], item[1].get("source_file", ""), item[1].get("line", 0)))
    return [record for _, record in scored[:limit]]


def _source_files(root: Path) -> list[Path]:
    kairos = root / "data" / "kairos"
    files: list[Path] = []
    if kairos.exists():
        for p in sorted(kairos.glob("KAIROS*.md")):
            if p.name == "KAIROS_MEMORY_INDEX.md":
                continue
            if "_proposed" in p.parts or "_rejected" in p.parts:
                continue
            files.append(p)
    core = root / "data" / "core" / "KAIROS_CORE.md"
    if core.exists():
        files.append(core)
    return files


def _parse_records(root: Path, source: Path) -> list[dict[str, Any]]:
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    starts: list[int] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _RECORD_START_RE.match(stripped):
            starts.append(i)
    if not starts:
        starts = [0]
    starts.append(len(lines))

    out: list[dict[str, Any]] = []
    for pos, start in enumerate(starts[:-1]):
        end = starts[pos + 1]
        block_lines = lines[start:end]
        block = "\n".join(block_lines).strip()
        if not block:
            continue
        title = block_lines[0].strip().lstrip("#").strip() if block_lines else source.stem
        date = _extract_date(block)
        summary = _summary(block_lines)
        topics = _topics(title + "\n" + block)
        aliases = _aliases(title, date, topics)
        out.append({
            "id": len(out),  # replaced by caller-local normalization below
            "title": title,
            "date": date,
            "month_day": date[5:10] if date else None,
            "topics": topics,
            "aliases": aliases,
            "summary": summary,
            "source_file": source.relative_to(root).as_posix(),
            "line": start + 1,
            "canonical": True,
        })

    # Make ids stable across the whole corpus by prefixing with source order later.
    rel = source.relative_to(root).as_posix()
    stable: list[dict[str, Any]] = []
    for local_id, record in enumerate(out):
        record = dict(record)
        record["id"] = _stable_id(rel, local_id)
        stable.append(record)
    return stable


def _extract_date(text: str) -> str | None:
    for line in text.splitlines():
        m = _DATE_LINE_RE.match(line.strip())
        if m:
            d = _normalize_date_text(m.group(1))
            if d:
                return d
    return _normalize_date_text(text)


def _normalize_date_text(text: str) -> str | None:
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _summary(lines: list[str], limit: int = 520) -> str:
    kept: list[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        if stripped.startswith(("DATE:", "LOCATION:", "OPERATOR:", "SESSION_ID:", "STATUS:")):
            continue
        kept.append(stripped)
        if len(" ".join(kept)) > limit:
            break
    text = " ".join(kept).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _topics(text: str) -> list[str]:
    topics = {topic for topic in _KNOWN_TOPICS if topic in text}
    topics.update(_IDENT_RE.findall(text))
    return sorted(topics)[:24]


def _aliases(title: str, date: str | None, topics: list[str]) -> list[str]:
    vals = {title}
    if "：" in title:
        vals.add(title.split("：", 1)[-1].strip())
    if ":" in title:
        vals.add(title.split(":", 1)[-1].strip())
    if date:
        vals.add(date)
        vals.add(date[5:10])
    vals.update(topics)
    return sorted(v for v in vals if v)[:32]


def _query_tokens(query: str) -> list[str]:
    q = query or ""
    tokens = set(_LATIN_RE.findall(q))
    tokens.update(_IDENT_RE.findall(q))
    d = _normalize_date_text(q)
    if d:
        tokens.add(d)
        tokens.add(d[5:10])
    for seg in _CJK_SEG_RE.findall(q):
        if len(seg) <= 8:
            tokens.add(seg)
        for n in (2, 3, 4):
            for i in range(0, max(0, len(seg) - n + 1)):
                tokens.add(seg[i:i + n])
    return sorted(tokens, key=lambda t: (-len(t), t))[:80]


def _records_by_ids(index: dict[str, Any], ids: list[int]) -> list[dict[str, Any]]:
    wanted = set(ids or [])
    return [record for record in index.get("records", []) if record.get("id") in wanted]


def _dedupe_index(index: dict[str, list[int]]) -> dict[str, list[int]]:
    return {key: sorted(set(vals)) for key, vals in sorted(index.items())}


def _stable_id(source_rel: str, local_id: int) -> int:
    digest = hashlib.sha1(f"{source_rel}:{local_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)
