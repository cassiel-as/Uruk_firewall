"""Evidence-filtered world forecast engine for URUK.

This module is deterministic. It does not claim to predict the future. It
turns filtered historical records and optional audited news inputs into
scenario weights, uncertainty, and traceable evidence.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APP_ROOT / "data"

SCHEMA_VERSION = "world_forecast.v1"

RATING_WEIGHT = {
    "VERIFIED": 1.0,
    "PROBABLE": 0.85,
    "INFERRED": 0.58,
    "UNVERIFIED": 0.22,
    "VERIFIED_INTERNAL": 0.95,
}

HORIZON_WEIGHT = {
    "short": 0.85,
    "medium": 1.0,
    "long": 1.16,
}

SIGNAL_KEYWORDS = {
    "kinetic_risk": (
        "war",
        "strike",
        "attack",
        "missile",
        "nuclear",
        "invasion",
        "military",
        "troop",
        "riot",
        "crackdown",
        "casualty",
        "killed",
        "dead",
    ),
    "institutional_stress": (
        "election",
        "court",
        "law",
        "state",
        "government",
        "regime",
        "coup",
        "legitimacy",
        "corruption",
        "sanction",
        "police",
    ),
    "coordination_speed": (
        "network",
        "platform",
        "social media",
        "viral",
        "mobilization",
        "protest",
        "uprising",
        "open-source",
        "telegram",
    ),
    "economic_pressure": (
        "market",
        "tariff",
        "trade",
        "inflation",
        "unemployment",
        "price",
        "energy",
        "oil",
        "gdp",
        "debt",
        "supply",
    ),
    "blackbox_pressure": (
        "blackbox",
        "opaque",
        "secret",
        "surveillance",
        "censorship",
        "algorithm",
        "misinformation",
        "classified",
    ),
    "cost_visibility": (
        "arrest",
        "prison",
        "injury",
        "wounded",
        "displaced",
        "refugee",
        "fine",
        "lawsuit",
        "casualty",
        "killed",
    ),
    "technology_acceleration": (
        "ai",
        "model",
        "robot",
        "chip",
        "compute",
        "cyber",
        "drone",
        "satellite",
        "biotech",
        "automation",
    ),
    "formatting_pressure": (
        "narrative",
        "framing",
        "propaganda",
        "label",
        "mandate",
        "generation",
        "neutral",
        "official",
    ),
    "resource_constraint": (
        "shortage",
        "food",
        "water",
        "climate",
        "drought",
        "flood",
        "grid",
        "electricity",
        "fuel",
    ),
    "diplomatic_buffer": (
        "treaty",
        "negotiation",
        "ceasefire",
        "alliance",
        "summit",
        "de-escalation",
        "agreement",
        "mediation",
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _stable_id(prefix: str, text: str) -> str:
    digest = hashlib.sha1((text or prefix).encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_\-]{2,}", text or "")]


def _query_terms(query: str) -> set[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "what",
        "will",
        "future",
        "forecast",
        "world",
        "risk",
        "about",
    }
    return {t for t in _tokens(query) if t not in stop}


def _excerpt(text: str, query_terms: Iterable[str], limit: int = 420) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) <= limit:
        return clean
    lowered = clean.lower()
    positions = [lowered.find(term) for term in query_terms if term and lowered.find(term) >= 0]
    start = max(0, min(positions) - 120) if positions else 0
    out = clean[start : start + limit].strip()
    return out


def _signal_hits(text: str) -> Dict[str, int]:
    lower = (text or "").lower()
    hits: Dict[str, int] = {}
    for signal, keywords in SIGNAL_KEYWORDS.items():
        count = 0
        for keyword in keywords:
            if " " in keyword:
                count += lower.count(keyword)
            else:
                count += len(re.findall(rf"\b{re.escape(keyword)}s?\b", lower))
        hits[signal] = count
    return hits


def _doc_relevance(query_terms: set[str], path: Path, text: str) -> float:
    haystack = f"{path.name} {text}".lower()
    if not query_terms:
        token_bonus = 0.0
    else:
        token_bonus = sum(1 for term in query_terms if term in haystack) / max(1, len(query_terms))
    signal_bonus = min(0.45, sum(_signal_hits(haystack).values()) / 120.0)
    cau_bonus = 0.08 if path.name.startswith("CAU-") else 0.0
    return round(token_bonus + signal_bonus + cau_bonus, 4)


def _history_files(data_dir: Path) -> List[Tuple[Path, str]]:
    root = Path(data_dir)
    files: List[Tuple[Path, str]] = []
    for folder, kind in (("causal_db", "historical_causal"), ("causal_records", "causal_record")):
        base = root / folder
        if not base.exists():
            continue
        for path in sorted(base.glob("*.md")):
            files.append((path, kind))
    return files


def build_history_evidence(
    *,
    query: str,
    data_dir: Optional[Path] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Select internal historical evidence relevant to the query."""
    root = Path(data_dir) if data_dir else DATA_DIR
    terms = _query_terms(query)
    ranked: List[Tuple[float, Path, str, str]] = []
    for path, kind in _history_files(root):
        text = _read_text(path)
        if not text:
            continue
        relevance = _doc_relevance(terms, path, text)
        if relevance <= 0.02 and terms:
            continue
        ranked.append((relevance, path, kind, text))

    ranked.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    evidence: List[Dict[str, Any]] = []
    for relevance, path, kind, text in ranked[: max(0, limit)]:
        rel_path = str(path.relative_to(APP_ROOT)) if path.is_relative_to(APP_ROOT) else str(path)
        title = path.stem.replace("_", " ")
        evidence.append(
            {
                "id": _stable_id("hist", rel_path),
                "kind": kind,
                "title": title,
                "source_file": rel_path.replace("\\", "/"),
                "coordinate": "internal_historical_causal_record",
                "rating": "VERIFIED_INTERNAL",
                "weight": RATING_WEIGHT["VERIFIED_INTERNAL"],
                "relevance": relevance,
                "excerpt": _excerpt(text, terms),
                "signals": _signal_hits(text),
            }
        )
    return evidence


def _audit_source(source: Dict[str, Any], registry: Any = None) -> Dict[str, Any]:
    if registry is None:
        from services.source_registry import source_registry

        registry = source_registry
    url = str(source.get("url") or "")
    text = str(source.get("text") or source.get("content") or "")
    return dict(registry.audit(url, text))


def filter_news_evidence(
    news_sources: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    registry: Any = None,
    limit: int = 12,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Audit externally supplied news sources and return filtered evidence.

    The function does not fetch live news. Callers must pass source objects that
    already contain URL and text/content. This keeps forecast runs reproducible.
    """
    raw_sources = list(news_sources or [])
    evidence: List[Dict[str, Any]] = []
    coordinates: set[str] = set()
    ratings: Dict[str, int] = {}

    for idx, src in enumerate(raw_sources[: max(0, limit)]):
        if not isinstance(src, dict):
            continue
        text = str(src.get("text") or src.get("content") or "")
        url = str(src.get("url") or "")
        if not text and not url:
            continue
        audit = _audit_source(src, registry)
        rating = audit.get("rating") or "UNVERIFIED"
        coordinate = audit.get("coordinate") or "unknown_unverified"
        coordinates.add(coordinate)
        ratings[rating] = ratings.get(rating, 0) + 1
        title = str(src.get("title") or audit.get("domain") or f"news source {idx + 1}")
        evidence.append(
            {
                "id": _stable_id("news", f"{url}:{idx}:{title}"),
                "kind": "news_source",
                "title": title[:120],
                "url": url,
                "domain": audit.get("domain") or "",
                "coordinate": coordinate,
                "rating": rating,
                "base_rating": audit.get("base_rating") or rating,
                "weight": RATING_WEIGHT.get(rating, RATING_WEIGHT["UNVERIFIED"]),
                "published_at": src.get("published_at") or src.get("date") or "",
                "excerpt": _excerpt(text, _query_terms(title)),
                "signals": _signal_hits(f"{title}\n{text}"),
                "audit": audit,
            }
        )

    flags: List[str] = []
    if not raw_sources:
        flags.append("no_live_news_input")
    if raw_sources and len(evidence) < 3:
        flags.append("insufficient_news_sources")
    if raw_sources and len(coordinates) < 2:
        flags.append("insufficient_coordinate_diversity")
    if any(item.get("rating") == "UNVERIFIED" for item in evidence):
        flags.append("contains_unverified_news")

    return evidence, {
        "source_count": len(evidence),
        "coordinate_count": len(coordinates),
        "coordinates": sorted(coordinates),
        "ratings": ratings,
        "flags": flags,
    }


def _aggregate_signals(evidence: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    totals = {signal: 0.0 for signal in SIGNAL_KEYWORDS}
    total_weight = 0.0
    for item in evidence:
        weight = float(item.get("weight") or 0.0) * float(item.get("relevance") or 1.0)
        total_weight += max(0.05, weight)
        signals = item.get("signals") or {}
        for signal in totals:
            hits = float(signals.get(signal) or 0.0)
            totals[signal] += min(1.0, hits / 5.0) * max(0.05, weight)
    if total_weight <= 0:
        return {signal: 0.0 for signal in totals}
    return {signal: round(_clamp(value / total_weight), 4) for signal, value in totals.items()}


def _score_scenarios(signals: Dict[str, float], horizon: str) -> List[Dict[str, Any]]:
    h = HORIZON_WEIGHT.get(horizon, HORIZON_WEIGHT["medium"])
    s = lambda key: float(signals.get(key) or 0.0)
    raw = {
        "stabilization": 0.24 + 0.34 * s("diplomatic_buffer") - 0.22 * s("kinetic_risk") - 0.12 * s("institutional_stress"),
        "escalation": 0.18 + h * (0.34 * s("kinetic_risk") + 0.16 * s("resource_constraint") + 0.13 * s("cost_visibility") + 0.12 * s("formatting_pressure")) - 0.12 * s("diplomatic_buffer"),
        "fragmentation": 0.2 + h * (0.22 * s("institutional_stress") + 0.18 * s("economic_pressure") + 0.12 * s("coordination_speed") + 0.12 * s("blackbox_pressure") + 0.1 * s("formatting_pressure")),
        "phase_transition": 0.14 + h * (0.28 * s("technology_acceleration") + 0.2 * s("coordination_speed") + 0.12 * s("blackbox_pressure") + 0.1 * s("institutional_stress")),
        "managed_continuity": 0.28 + 0.18 * s("diplomatic_buffer") + 0.06 * s("economic_pressure") - 0.1 * s("kinetic_risk"),
    }
    raw = {key: max(0.01, value) for key, value in raw.items()}
    total = sum(raw.values()) or 1.0

    scenarios: List[Dict[str, Any]] = []
    for sid, value in raw.items():
        p = value / total
        if p >= 0.3:
            band = "high"
        elif p >= 0.22:
            band = "elevated"
        elif p >= 0.15:
            band = "watch"
        else:
            band = "low"
        scenarios.append(
            {
                "id": sid,
                "label": sid.replace("_", " "),
                "relative_weight": round(p, 4),
                "band": band,
                "drivers": _scenario_drivers(sid, signals),
            }
        )
    scenarios.sort(key=lambda item: item["relative_weight"], reverse=True)
    return scenarios


def _scenario_drivers(scenario_id: str, signals: Dict[str, float]) -> List[str]:
    driver_map = {
        "stabilization": ("diplomatic_buffer", "kinetic_risk", "institutional_stress"),
        "escalation": ("kinetic_risk", "resource_constraint", "cost_visibility", "formatting_pressure"),
        "fragmentation": ("institutional_stress", "economic_pressure", "coordination_speed", "blackbox_pressure"),
        "phase_transition": ("technology_acceleration", "coordination_speed", "blackbox_pressure"),
        "managed_continuity": ("diplomatic_buffer", "economic_pressure", "kinetic_risk"),
    }
    keys = driver_map.get(scenario_id, ())
    ranked = sorted(keys, key=lambda key: float(signals.get(key) or 0.0), reverse=True)
    return [key for key in ranked if float(signals.get(key) or 0.0) > 0.02][:4]


def _uncertainty(evidence: Sequence[Dict[str, Any]], news_summary: Dict[str, Any]) -> float:
    count = len(evidence)
    weighted = sum(float(item.get("weight") or 0.0) for item in evidence)
    uncertainty = 0.82
    uncertainty -= min(0.28, count * 0.025)
    uncertainty -= min(0.18, weighted * 0.015)
    if news_summary.get("coordinate_count", 0) >= 2:
        uncertainty -= 0.12
    for flag in news_summary.get("flags") or []:
        if flag == "no_live_news_input":
            uncertainty += 0.08
        elif flag == "insufficient_coordinate_diversity":
            uncertainty += 0.12
        elif flag == "insufficient_news_sources":
            uncertainty += 0.08
        elif flag == "contains_unverified_news":
            uncertainty += 0.05
    return round(_clamp(uncertainty), 4)


def _warnings(evidence: Sequence[Dict[str, Any]], news_summary: Dict[str, Any], uncertainty: float) -> List[str]:
    warnings = [
        "not_oracle: output is scenario weighting, not a guaranteed prediction",
        "assumptions_must_be_rechecked_when_new_evidence_arrives",
    ]
    if not evidence:
        warnings.append("no_evidence_available")
    warnings.extend(news_summary.get("flags") or [])
    if uncertainty >= 0.75:
        warnings.append("high_uncertainty")
    return warnings


def forecast_world(
    *,
    input_text: str = "",
    horizon: str = "medium",
    data_dir: Optional[Path] = None,
    news_sources: Optional[Sequence[Dict[str, Any]]] = None,
    source_registry: Any = None,
    history_limit: int = 10,
    news_limit: int = 12,
) -> Dict[str, Any]:
    """Build a deterministic future-scenario forecast from filtered evidence."""
    safe_horizon = horizon if horizon in HORIZON_WEIGHT else "medium"
    root = Path(data_dir) if data_dir else DATA_DIR
    history = build_history_evidence(query=input_text, data_dir=root, limit=history_limit)
    news, news_summary = filter_news_evidence(news_sources, registry=source_registry, limit=news_limit)
    evidence = history + news
    signals = _aggregate_signals(evidence)
    scenarios = _score_scenarios(signals, safe_horizon)
    uncertainty = _uncertainty(evidence, news_summary)
    primary = scenarios[0] if scenarios else None

    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "input_text": input_text,
        "horizon": safe_horizon,
        "method": {
            "name": "filtered_evidence_causal_scenario_weighting",
            "deterministic": True,
            "uses_llm": False,
            "history_prior": "data/causal_db + data/causal_records",
            "news_filter": "source_registry coordinate audit; live fetch is caller-controlled",
        },
        "evidence_counts": {
            "history": len(history),
            "news": len(news),
            "total": len(evidence),
        },
        "news_filter": news_summary,
        "signals": signals,
        "scenarios": scenarios,
        "forecast": {
            "primary_scenario": primary.get("id") if primary else "",
            "primary_band": primary.get("band") if primary else "none",
            "uncertainty": uncertainty,
            "interpretation": _interpret(primary, uncertainty),
        },
        "evidence": evidence[: history_limit + news_limit],
        "warnings": _warnings(evidence, news_summary, uncertainty),
    }


def _interpret(primary: Optional[Dict[str, Any]], uncertainty: float) -> str:
    if not primary:
        return "No usable evidence; do not infer a future state."
    base = f"Highest current scenario weight: {primary['id']} ({primary['band']})."
    if uncertainty >= 0.75:
        return base + " Evidence is too thin for operational decisions."
    if uncertainty >= 0.55:
        return base + " Use as a watchlist, then refresh with current sources."
    return base + " Use as a bounded scenario prior, not a prediction."


__all__ = [
    "SCHEMA_VERSION",
    "build_history_evidence",
    "filter_news_evidence",
    "forecast_world",
]
