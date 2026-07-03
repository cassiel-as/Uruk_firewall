"""Generated Coordinate Theory card index.

The long-form Coordinate corpus stays in markdown/json.  This index gives the
runtime a compact deterministic lookup layer for routing, UI trace, and
benchmark telemetry.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from services.coordinate_knowledge import load_coordinate_cards


INDEX_REL = Path("data/theory/COORDINATE_INDEX.json")
CARDS_REL = Path("data/theory/coordinate_knowledge_cards.json")
DOC_REL = Path("data/theory/COORDINATE_KNOWLEDGE_CARDS.md")
INDEXER_REL = Path("services/coordinate_index.py")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}|[\u4e00-\u9fff]{2,}")


def get_coordinate_index(root: Path) -> dict[str, Any]:
    root = Path(root)
    index_path = root / INDEX_REL
    sources = [p for p in (root / CARDS_REL, root / DOC_REL, root / INDEXER_REL) if p.exists()]
    latest_source_mtime = max((p.stat().st_mtime for p in sources), default=0.0)
    if index_path.exists() and index_path.stat().st_mtime >= latest_source_mtime:
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return build_coordinate_index(root, write=True)


def build_coordinate_index(root: Path, *, write: bool = True) -> dict[str, Any]:
    root = Path(root)
    cards = load_coordinate_cards(root=root)
    indexed_cards: list[dict[str, Any]] = []
    trigger_index: dict[str, list[str]] = {}
    for card in cards:
        data = card.to_dict()
        data["source_file"] = DOC_REL.as_posix()
        data["doc_id"] = "theory.coordinate.cards"
        data["keywords"] = _keywords_for_card(data)
        indexed_cards.append(data)
        for token in data["keywords"]:
            trigger_index.setdefault(token, []).append(card.id)

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_files": [CARDS_REL.as_posix(), DOC_REL.as_posix(), INDEXER_REL.as_posix()],
        "source_sha256": _source_sha256(root),
        "card_count": len(indexed_cards),
        "cards": indexed_cards,
        "trigger_index": {k: sorted(set(v)) for k, v in sorted(trigger_index.items())},
    }
    if write:
        index_path = root / INDEX_REL
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def search_coordinate_index(root: Path, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
    index = get_coordinate_index(root)
    tokens = _query_tokens(query)
    if not tokens:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for card in index.get("cards", []) or []:
        keywords = set(card.get("keywords") or [])
        score = len(tokens & keywords)
        if score:
            scored.append((score, card))
    scored.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    out: list[dict[str, Any]] = []
    for score, card in scored[:limit]:
        item = dict(card)
        item["score"] = score
        item["matched_terms"] = sorted(tokens & set(card.get("keywords") or []))[:10]
        out.append(item)
    return out


def _keywords_for_card(card: dict[str, Any]) -> list[str]:
    priority_chunks: list[str] = []
    for key in ("triggers", "use_when", "evaluation_terms"):
        priority_chunks.extend(str(item) for item in card.get(key) or [])

    chunks: list[str] = []
    for key in (
        "id",
        "title",
        "claim",
        "prompt_guidance",
        "test",
    ):
        chunks.append(str(card.get(key) or ""))

    keywords: list[str] = []
    seen: set[str] = set()
    for token in sorted(_query_tokens("\n".join(priority_chunks))):
        if token not in seen:
            keywords.append(token)
            seen.add(token)
    for token in sorted(_query_tokens("\n".join(chunks))):
        if token not in seen:
            keywords.append(token)
            seen.add(token)
    return keywords[:128]


def _query_tokens(text: str) -> set[str]:
    raw = str(text or "").casefold()
    tokens: set[str] = set()
    for match in _WORD_RE.findall(raw):
        tokens.add(match)
        if re.fullmatch(r"[\u4e00-\u9fff]{3,}", match):
            for n in (2, 3, 4):
                for i in range(0, max(0, len(match) - n + 1)):
                    tokens.add(match[i:i + n])
    return {token for token in tokens if token.strip()}


def _source_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for rel in (CARDS_REL, DOC_REL, INDEXER_REL):
        path = Path(root) / rel
        if path.exists():
            digest.update(rel.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()
