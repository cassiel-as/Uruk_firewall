"""
Coordinate theory knowledge-card utilities.

This layer turns the long-form Coordinate Theory corpus into small,
query-selectable cards that can be cited, traced, and used to evaluate system
outputs. The user request is only used for routing/selecting cards.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).parent.parent
CARDS_PATH = ROOT / "data" / "theory" / "coordinate_knowledge_cards.json"
CARDS_DOC_PATH = ROOT / "data" / "theory" / "COORDINATE_KNOWLEDGE_CARDS.md"


@dataclass(frozen=True)
class CoordinateCard:
    id: str
    title: str
    claim: str
    use_when: tuple[str, ...]
    not_for: tuple[str, ...]
    false_positive_guards: tuple[str, ...]
    triggers: tuple[str, ...]
    prompt_guidance: str
    test: str
    evaluation_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "claim": self.claim,
            "use_when": list(self.use_when),
            "not_for": list(self.not_for),
            "false_positive_guards": list(self.false_positive_guards),
            "triggers": list(self.triggers),
            "prompt_guidance": self.prompt_guidance,
            "test": self.test,
            "evaluation_terms": list(self.evaluation_terms),
            "forbidden_terms": list(self.forbidden_terms),
        }


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _norm(text: str) -> str:
    return str(text or "").casefold()


def _contains(text: str, term: str) -> bool:
    if not term:
        return False
    needle = _norm(term)
    haystack = _norm(text)
    if re.fullmatch(r"[a-z0-9_\-]{1,4}", needle):
        return re.search(rf"(?<![a-z0-9_\-]){re.escape(needle)}(?![a-z0-9_\-])", haystack) is not None
    return needle in haystack


def load_coordinate_cards(*, root: Path = ROOT, path: Optional[Path] = None) -> List[CoordinateCard]:
    cards_path = Path(path) if path else Path(root) / "data" / "theory" / "coordinate_knowledge_cards.json"
    payload = json.loads(cards_path.read_text(encoding="utf-8"))
    out: List[CoordinateCard] = []
    for raw in payload.get("cards", []) or []:
        evaluation = raw.get("evaluation") or {}
        out.append(CoordinateCard(
            id=str(raw.get("id") or ""),
            title=str(raw.get("title") or ""),
            claim=str(raw.get("claim") or ""),
            use_when=_tuple(raw.get("use_when")),
            not_for=_tuple(raw.get("not_for")),
            false_positive_guards=_tuple(raw.get("false_positive_guards")),
            triggers=_tuple(raw.get("triggers")),
            prompt_guidance=str(raw.get("prompt_guidance") or ""),
            test=str(raw.get("test") or ""),
            evaluation_terms=_tuple(evaluation.get("requires_any_terms")),
            forbidden_terms=_tuple(evaluation.get("forbidden_terms")),
        ))
    return [card for card in out if card.id and card.claim]


def coordinate_cards_health(*, root: Path = ROOT) -> Dict[str, Any]:
    cards_path = Path(root) / "data" / "theory" / "coordinate_knowledge_cards.json"
    doc_path = Path(root) / "data" / "theory" / "COORDINATE_KNOWLEDGE_CARDS.md"
    issues: List[Dict[str, Any]] = []
    try:
        cards = load_coordinate_cards(root=root)
    except Exception as exc:
        return {
            "ok": False,
            "count": 0,
            "issues": [{"severity": "P0", "code": "cards_unreadable", "message": f"{type(exc).__name__}: {exc}"}],
        }

    seen = set()
    for card in cards:
        if card.id in seen:
            issues.append({"severity": "P0", "code": "duplicate_card_id", "card_id": card.id})
        seen.add(card.id)
        if not card.triggers:
            issues.append({"severity": "P1", "code": "card_missing_triggers", "card_id": card.id})
        if not card.evaluation_terms:
            issues.append({"severity": "P2", "code": "card_missing_eval_terms", "card_id": card.id})
        if not card.false_positive_guards:
            issues.append({"severity": "P2", "code": "card_missing_false_positive_guards", "card_id": card.id})

    if not doc_path.exists():
        issues.append({"severity": "P1", "code": "cards_markdown_missing", "path": str(doc_path)})

    fatal = sum(1 for item in issues if item.get("severity") == "P0")
    return {
        "ok": fatal == 0 and bool(cards),
        "count": len(cards),
        "path": str(cards_path.resolve()),
        "markdown_path": str(doc_path.resolve()),
        "sha256": hashlib.sha256(cards_path.read_bytes()).hexdigest() if cards_path.exists() else None,
        "issues": issues,
    }


def select_coordinate_cards(query: str, *, max_cards: int = 4, root: Path = ROOT) -> List[Dict[str, Any]]:
    """Select relevant Coordinate Theory cards for a query.

    Matching is intentionally conservative: a card must match its explicit
    trigger terms. This keeps the theory layer from polluting ordinary chats.
    """
    text = str(query or "")
    if not text.strip():
        return []

    selected: List[tuple[int, CoordinateCard, List[str]]] = []
    for card in load_coordinate_cards(root=root):
        matched = [term for term in card.triggers if _contains(text, term)]
        if not matched:
            continue
        score = len(matched)
        if any(_contains(text, term) for term in card.use_when):
            score += 2
        selected.append((score, card, matched))

    selected.sort(key=lambda item: (-item[0], item[1].id))
    out: List[Dict[str, Any]] = []
    for score, card, matched in selected[:max_cards]:
        data = card.to_dict()
        data["score"] = score
        data["matched_terms"] = matched[:8]
        data["source_file"] = "data/theory/COORDINATE_KNOWLEDGE_CARDS.md"
        data["doc_id"] = "theory.coordinate.cards"
        data["doc_layer"] = "theory"
        data["doc_canonical"] = True
        data["text"] = f"{card.title}: {card.claim} 測試: {card.test}"
        data["section"] = card.id
        return_score = float(score)
        data["retrieval_score"] = return_score
        out.append(data)
    return out


def format_coordinate_cards_for_prompt(cards: List[Dict[str, Any]]) -> str:
    if not cards:
        return ""
    lines = [
        "━━━ Coordinate knowledge cards — output self-check, not user judgement ━━━",
        "Use the request only to select relevant cards. Do not score, diagnose, or audit the user.",
        "Use these cards to keep your own answer clear, grounded, bounded, and useful.",
    ]
    for card in cards:
        lines.extend([
            f"[{card.get('id')}] {card.get('title')}",
            f"claim: {card.get('claim')}",
            f"use: {card.get('prompt_guidance')}",
            f"test: {card.get('test')}",
            f"guard: {', '.join(card.get('false_positive_guards') or [])}",
        ])
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines) + "\n\n"


def coordinate_cards_block(query: str, *, max_cards: int = 4, root: Path = ROOT) -> tuple[str, List[Dict[str, Any]]]:
    cards = select_coordinate_cards(query, max_cards=max_cards, root=root)
    return format_coordinate_cards_for_prompt(cards), cards


def evaluate_coordinate_output(
    query: str,
    answer: str,
    *,
    root: Path = ROOT,
    max_cards: int = 4,
) -> Dict[str, Any]:
    """Deterministically check whether the system output used relevant cards.

    `query` selects relevant cards; only `answer` is evaluated. This avoids
    turning the Coordinate layer into a judgement of the user's input.
    """
    cards = select_coordinate_cards(query, max_cards=max_cards, root=root)
    answer_text = str(answer or "")
    coordinate_jargon = (
        "座標說", "座標", "隱藏座標", "未申報座標", "framing",
        "框架", "代價落點", "source coordinate", "coordinate",
    )
    guard_terms = (
        "不適用", "唔適用", "不需要", "唔需要", "普通 factual",
        "普通查詢", "直接回答", "唔係座標問題", "不是座標問題",
    )
    hidden_coordinate_terms = ("隱藏座標", "未申報座標", "假中立", "neutral", "座標透明")
    cost_locus_terms = ("代價落", "代價位置", "誰承擔", "邊個承擔", "成本落", "身體", "物理代價")
    source_trace_terms = ("來源", "引用", "trace", "harness", "episode", "manifest", "RAG", "驗證")

    def _any(terms: Iterable[str]) -> bool:
        return any(_contains(answer_text, term) for term in terms)

    over_applied = (not cards) and _any(coordinate_jargon) and not _any(guard_terms)
    if not cards:
        return {
            "active": False,
            "target": "system_output",
            "input_role": "routing_only",
            "coordinate_use": "over_applied" if over_applied else "not_applicable",
            "over_applied": over_applied,
            "hidden_coordinate_detected": _any(hidden_coordinate_terms),
            "cost_locus_present": _any(cost_locus_terms),
            "source_trace_present": _any(source_trace_terms),
            "score": None,
            "selected_count": 0,
            "passed_count": 0,
            "missing_count": 0,
            "missing": [],
            "matched": [],
            "selected_card_ids": [],
            "notes": (
                ["No coordinate card selected, but answer appears to over-apply Coordinate Theory."]
                if over_applied else
                ["No coordinate card selected; coordinate layer stayed inactive."]
            ),
        }

    matched: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    forbidden_hits: List[Dict[str, Any]] = []
    for card in cards:
        terms = card.get("evaluation_terms") or []
        found = [term for term in terms if _contains(answer_text, term)]
        forbidden = [term for term in card.get("forbidden_terms") or [] if _contains(answer_text, term)]
        item = {
            "card_id": card.get("id"),
            "title": card.get("title"),
            "test": card.get("test"),
            "matched_terms": found,
            "forbidden_terms": forbidden,
        }
        if found:
            matched.append(item)
        else:
            missing.append(item)
        if forbidden:
            forbidden_hits.append(item)

    passed = len(matched)
    score = passed / len(cards) if cards else 0.0
    if forbidden_hits:
        coordinate_use = "misused"
    elif score >= 0.75:
        coordinate_use = "good"
    elif score > 0:
        coordinate_use = "partial"
    else:
        coordinate_use = "missing"
    return {
        "active": True,
        "target": "system_output",
        "input_role": "routing_only",
        "coordinate_use": coordinate_use,
        "over_applied": False,
        "hidden_coordinate_detected": _any(hidden_coordinate_terms),
        "cost_locus_present": _any(cost_locus_terms),
        "source_trace_present": _any(source_trace_terms),
        "score": round(score, 3),
        "selected_count": len(cards),
        "selected_card_ids": [card.get("id") for card in cards],
        "passed_count": passed,
        "missing_count": len(missing),
        "forbidden_count": len(forbidden_hits),
        "matched": matched,
        "missing": missing,
        "forbidden": forbidden_hits,
    }


def evaluate_coordinate_grounding(
    query: str,
    answer: str,
    *,
    root: Path = ROOT,
    max_cards: int = 4,
) -> Dict[str, Any]:
    """Backward-compatible alias for the output-focused evaluator."""
    return evaluate_coordinate_output(query, answer, root=root, max_cards=max_cards)


def extract_card_ids_from_trace(trace: List[Dict[str, Any]]) -> List[str]:
    ids: List[str] = []
    for entry in trace or []:
        for hit in entry.get("hits") or []:
            card_id = hit.get("card_id") or hit.get("id")
            if isinstance(card_id, str) and card_id.startswith("coordinate."):
                ids.append(card_id)
    return sorted(set(ids))
