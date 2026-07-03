"""Geo-temporal world graph for historical anchors and forecast correction.

The graph uses real latitude/longitude for historical events. Future points are
marked as projections and must not be treated as observed history.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.world_forecast import forecast_world, filter_news_evidence


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APP_ROOT / "data"
EVENTS_PATH = DATA_DIR / "world" / "historical_events.json"
SCHEMA_VERSION = "world_geotimeline.v1"


GAZETTEER = {
    "admiralty": {"location": "Admiralty, Hong Kong", "lat": 22.2795, "lon": 114.1655, "aliases": ["hong kong", "hk", "admiralty"]},
    "berlin": {"location": "Berlin, Germany", "lat": 52.5163, "lon": 13.3777, "aliases": ["berlin"]},
    "cairo": {"location": "Cairo, Egypt", "lat": 30.0444, "lon": 31.2357, "aliases": ["cairo", "tahrir"]},
    "dhaka": {"location": "Dhaka, Bangladesh", "lat": 23.8103, "lon": 90.4125, "aliases": ["dhaka", "bangladesh"]},
    "gaza": {"location": "Gaza City, Gaza", "lat": 31.5017, "lon": 34.4668, "aliases": ["gaza"]},
    "hiroshima": {"location": "Hiroshima, Japan", "lat": 34.3853, "lon": 132.4553, "aliases": ["hiroshima"]},
    "jerusalem": {"location": "Jerusalem", "lat": 31.7683, "lon": 35.2137, "aliases": ["jerusalem"]},
    "kyiv": {"location": "Kyiv, Ukraine", "lat": 50.4501, "lon": 30.5234, "aliases": ["kyiv", "kiev", "ukraine"]},
    "kursk": {"location": "Kursk, Russia", "lat": 51.7304, "lon": 36.1939, "aliases": ["kursk"]},
    "london": {"location": "London, United Kingdom", "lat": 51.5072, "lon": -0.1276, "aliases": ["london", "uk"]},
    "los_angeles": {"location": "Los Angeles, United States", "lat": 34.0522, "lon": -118.2437, "aliases": ["los angeles", "ucla"]},
    "moscow": {"location": "Moscow, Russia", "lat": 55.7558, "lon": 37.6173, "aliases": ["moscow", "russia"]},
    "nagasaki": {"location": "Nagasaki, Japan", "lat": 32.7503, "lon": 129.8779, "aliases": ["nagasaki"]},
    "new_york": {"location": "New York City, United States", "lat": 40.7128, "lon": -74.006, "aliases": ["new york", "nyc", "world trade center"]},
    "paris": {"location": "Paris, France", "lat": 48.8566, "lon": 2.3522, "aliases": ["paris", "france"]},
    "sarajevo": {"location": "Sarajevo, Bosnia and Herzegovina", "lat": 43.8563, "lon": 18.4131, "aliases": ["sarajevo"]},
    "tehran": {"location": "Tehran, Iran", "lat": 35.6892, "lon": 51.389, "aliases": ["tehran", "iran"]},
    "wittenberg": {"location": "Wittenberg, Germany", "lat": 51.866, "lon": 12.646, "aliases": ["wittenberg"]},
    "wuhan": {"location": "Wuhan, China", "lat": 30.5928, "lon": 114.3055, "aliases": ["wuhan"]},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date_key(value: str) -> Tuple[int, int, int, str]:
    match = re.search(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", value or "")
    if not match:
        return (9999, 12, 31, value or "")
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    return (year, month, day, value or "")


def _stable_id(prefix: str, text: str) -> str:
    import hashlib

    digest = hashlib.sha1((text or prefix).encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _terms(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "world", "future", "forecast", "risk"}
    return {t.lower() for t in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_\-]{2,}", text or "") if t.lower() not in stop}


def load_geo_events(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(data_dir) if data_dir else DATA_DIR
    path = root / "world" / "historical_events.json"
    if not path.exists():
        return {"schema_version": "uruk_geo_history.v1", "events": [], "links": []}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    events = [normalise_event(item) for item in payload.get("events") or [] if isinstance(item, dict)]
    links = [normalise_link(item) for item in payload.get("links") or [] if isinstance(item, dict)]
    return {"schema_version": payload.get("schema_version") or "uruk_geo_history.v1", "events": events, "links": links}


def normalise_event(item: Dict[str, Any]) -> Dict[str, Any]:
    lat = float(item.get("lat"))
    lon = float(item.get("lon"))
    projected = bool(item.get("projected") or False)
    event_type = str(item.get("type") or "event")
    temporal_state = str(
        item.get("temporal_state")
        or ("projected" if projected else "news" if event_type == "news_observation" else "historical")
    )
    return {
        "id": str(item.get("id") or _stable_id("evt", item.get("title") or "")),
        "date": str(item.get("date") or ""),
        "title": str(item.get("title") or "untitled event"),
        "location": str(item.get("location") or ""),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "type": event_type,
        "temporal_state": temporal_state,
        "source_ref": str(item.get("source_ref") or ""),
        "summary": str(item.get("summary") or ""),
        "tags": [str(t) for t in (item.get("tags") or []) if t],
        "projected": projected,
        "observed": not projected,
        "confidence": float(item.get("confidence") or (0.95 if not projected else 0.35)),
        "source_kind": str(item.get("source_kind") or ("model" if projected else "curated")),
        "source_rating": str(item.get("source_rating") or ""),
    }


def normalise_link(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": str(item.get("source") or ""),
        "target": str(item.get("target") or ""),
        "kind": str(item.get("kind") or "related"),
        "weight": round(max(0.01, min(1.0, float(item.get("weight") or 0.3))), 4),
        "evidence_type": str(item.get("evidence_type") or "curated"),
        "shared_tags": [str(tag) for tag in (item.get("shared_tags") or []) if tag],
        "explanation": str(item.get("explanation") or ""),
    }


def _event_relevance(event: Dict[str, Any], query_terms: set[str]) -> float:
    if not query_terms:
        return 0.5
    haystack = " ".join(
        [
            event.get("title", ""),
            event.get("location", ""),
            event.get("type", ""),
            event.get("summary", ""),
            " ".join(event.get("tags") or []),
        ]
    ).lower()
    hits = sum(1 for term in query_terms if term in haystack)
    return hits / max(1, len(query_terms))


def _filter_events(events: Sequence[Dict[str, Any]], query: str, limit: int) -> List[Dict[str, Any]]:
    terms = _terms(query)
    ranked = []
    for event in events:
        relevance = _event_relevance(event, terms)
        if terms and relevance <= 0:
            continue
        ranked.append((relevance, event))
    ranked.sort(key=lambda pair: (pair[0], _date_key(pair[1].get("date", ""))), reverse=True)
    selected = [dict(event, relevance=round(relevance, 4)) for relevance, event in ranked[: max(1, limit)]]
    selected.sort(key=lambda event: _date_key(event.get("date", "")))
    return selected


def _find_place(source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if source.get("lat") is not None and source.get("lon") is not None:
        return {
            "location": str(source.get("location") or source.get("place") or "declared coordinate"),
            "lat": float(source.get("lat")),
            "lon": float(source.get("lon")),
        }
    text = " ".join(
        str(source.get(key) or "")
        for key in ("location", "place", "title", "text", "content", "summary", "snippet")
    ).lower()
    for place in GAZETTEER.values():
        for alias in place["aliases"]:
            if alias in text:
                return {"location": place["location"], "lat": place["lat"], "lon": place["lon"]}
    return None


def _source_date(source: Dict[str, Any]) -> str:
    for key in ("published_at", "date", "fetched_at"):
        if source.get(key):
            return str(source.get(key))[:10]
    text = " ".join(str(source.get(key) or "") for key in ("title", "text", "content"))
    match = re.search(r"(20\d{2}-\d{2}-\d{2}|20\d{2}-\d{2}|20\d{2})", text)
    if match:
        return match.group(1)
    return _now()[:10]


def extract_news_geo_events(news_sources: Sequence[Dict[str, Any]], news_evidence: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    evidence_by_url = {str(item.get("url") or ""): item for item in news_evidence if item.get("url")}
    evidence_by_title = {str(item.get("title") or ""): item for item in news_evidence if item.get("title")}
    for idx, source in enumerate(news_sources):
        if not isinstance(source, dict):
            continue
        place = _find_place(source)
        if not place:
            continue
        source_title = str(source.get("title") or "")
        evidence = evidence_by_url.get(str(source.get("url") or "")) or evidence_by_title.get(source_title) or {}
        title = str(source_title or evidence.get("title") or f"News observation {idx + 1}")
        text = str(source.get("text") or source.get("content") or "")
        signals = evidence.get("signals") or {}
        tags = [key for key, value in signals.items() if value]
        events.append(
            normalise_event(
                {
                    "id": _stable_id("newsgeo", f"{source.get('url', '')}:{title}:{idx}"),
                    "date": _source_date(source),
                    "title": title[:120],
                    "location": place["location"],
                    "lat": place["lat"],
                    "lon": place["lon"],
                    "type": "news_observation",
                    "source_ref": str(source.get("url") or ""),
                    "summary": text[:240],
                    "tags": tags,
                    "confidence": float(evidence.get("weight") or 0.22),
                    "source_kind": "audited_news",
                    "source_rating": str(evidence.get("rating") or "UNVERIFIED"),
                    "temporal_state": "news",
                }
            )
        )
    return events


def _distance_km(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    lat1 = math.radians(float(a.get("lat") or 0.0))
    lat2 = math.radians(float(b.get("lat") or 0.0))
    dlat = lat2 - lat1
    dlon = math.radians(float(b.get("lon") or 0.0) - float(a.get("lon") or 0.0))
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def _auto_links(events: Sequence[Dict[str, Any]], existing: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing_keys = {(item.get("source"), item.get("target"), item.get("kind")) for item in existing}
    links: List[Dict[str, Any]] = []
    sorted_events = sorted(events, key=lambda event: _date_key(event.get("date", "")))
    for idx, event in enumerate(sorted_events):
        tags = set(event.get("tags") or [])
        best: Optional[Tuple[float, Dict[str, Any], str]] = None
        for prior in sorted_events[:idx]:
            shared = tags & set(prior.get("tags") or [])
            if not shared:
                continue
            distance = _distance_km(event, prior)
            score = min(1.0, len(shared) / 4.0 + max(0.0, 1.0 - distance / 9000.0) * 0.25)
            if best is None or score > best[0]:
                best = (score, prior, "tag_overlap:" + ",".join(sorted(shared)[:3]))
        if best and best[0] >= 0.28:
            link = {
                "source": best[1]["id"],
                "target": event["id"],
                "kind": best[2],
                "weight": round(best[0], 4),
                "evidence_type": "inferred_tag_overlap",
                "shared_tags": sorted(tags & set(best[1].get("tags") or []))[:6],
            }
            key = (link["source"], link["target"], link["kind"])
            if key not in existing_keys:
                links.append(link)
    return links


def _centroid(events: Sequence[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    usable = [event for event in events if event.get("lat") is not None and event.get("lon") is not None]
    if not usable:
        return None
    return {
        "lat": round(sum(float(event["lat"]) for event in usable) / len(usable), 6),
        "lon": round(sum(float(event["lon"]) for event in usable) / len(usable), 6),
    }


def _parse_iso_date(value: str) -> Optional[datetime]:
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc)
    except ValueError:
        return None


def _projection_date(horizon: str) -> str:
    days = {
        "short": 30,
        "medium": 180,
        "long": 365,
        "strategic": 730,
    }.get(str(horizon or "").lower(), 180)
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def _link_explanation(link: Dict[str, Any]) -> str:
    if link.get("explanation"):
        return str(link["explanation"])
    kind = str(link.get("kind") or "related")
    evidence_type = str(link.get("evidence_type") or "curated")
    if evidence_type == "model_projection":
        return "Observed evidence contributes to this projected pressure centre; this is not a proven causal claim."
    if evidence_type == "inferred_tag_overlap":
        tags = ", ".join(link.get("shared_tags") or []) or "shared signals"
        return f"Automatically inferred from shared signals: {tags}."
    return f"Curated causal or analytical relation: {kind.replace('_', ' ')}."


def _enrich_links(links: Sequence[Dict[str, Any]], events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {event["id"]: event for event in events}
    enriched: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    for raw in links:
        link = normalise_link(raw)
        key = (link["source"], link["target"], link["kind"])
        if key in seen:
            continue
        seen.add(key)
        source = by_id.get(link["source"])
        target = by_id.get(link["target"])
        if not source or not target:
            continue
        source_date = _parse_iso_date(source.get("date", ""))
        target_date = _parse_iso_date(target.get("date", ""))
        gap_days = abs((target_date - source_date).days) if source_date and target_date else None
        enriched.append(
            {
                **link,
                "source_title": source.get("title") or link["source"],
                "target_title": target.get("title") or link["target"],
                "distance_km": round(_distance_km(source, target), 1),
                "time_gap_days": gap_days,
                "explanation": _link_explanation(link),
            }
        )
    return enriched


def _scenario_deltas(baseline: Dict[str, Any], corrected: Dict[str, Any]) -> Dict[str, float]:
    base = {item["id"]: float(item.get("relative_weight") or 0.0) for item in baseline.get("scenarios") or []}
    corr = {item["id"]: float(item.get("relative_weight") or 0.0) for item in corrected.get("scenarios") or []}
    keys = sorted(set(base) | set(corr))
    return {key: round(corr.get(key, 0.0) - base.get(key, 0.0), 4) for key in keys}


def _projection_event(corrected: Dict[str, Any], source_events: Sequence[Dict[str, Any]], horizon: str) -> Optional[Dict[str, Any]]:
    center = _centroid(source_events)
    primary = (corrected.get("forecast") or {}).get("primary_scenario") or ""
    if not center or not primary:
        return None
    return normalise_event(
        {
            "id": _stable_id("projection", f"{primary}:{center['lat']}:{center['lon']}:{horizon}"),
            "date": _projection_date(horizon),
            "title": f"Projected pressure center: {primary}",
            "location": "Forecast pressure centroid",
            "lat": center["lat"],
            "lon": center["lon"],
            "type": "future_projection",
            "source_ref": "services/world_forecast.py",
            "summary": "Projected node from scenario weights; not an observed historical event.",
            "tags": ["projection", primary],
            "projected": True,
            "confidence": max(0.05, 1.0 - float((corrected.get("forecast") or {}).get("uncertainty") or 0.9)),
            "source_kind": "scenario_projection",
            "temporal_state": "projected",
        }
    )


def build_geo_timeline(
    *,
    input_text: str = "",
    horizon: str = "medium",
    data_dir: Optional[Path] = None,
    news_sources: Optional[Sequence[Dict[str, Any]]] = None,
    source_registry: Any = None,
    event_limit: int = 80,
) -> Dict[str, Any]:
    root = Path(data_dir) if data_dir else DATA_DIR
    source_payload = load_geo_events(root)
    history_events = _filter_events(source_payload["events"], input_text, event_limit)
    raw_news = [dict(item) for item in (news_sources or []) if isinstance(item, dict)]
    news_evidence, news_filter = filter_news_evidence(raw_news, registry=source_registry)
    news_events = extract_news_geo_events(raw_news, news_evidence)

    baseline = forecast_world(input_text=input_text, horizon=horizon, data_dir=root, news_sources=[], source_registry=source_registry)
    corrected = forecast_world(input_text=input_text, horizon=horizon, data_dir=root, news_sources=raw_news, source_registry=source_registry)

    events = history_events + news_events
    projection_sources = news_events or history_events[-5:]
    projection = _projection_event(corrected, projection_sources, horizon)
    if projection:
        events.append(projection)

    allowed_ids = {event["id"] for event in events}
    curated_links = [link for link in source_payload["links"] if link.get("source") in allowed_ids and link.get("target") in allowed_ids]
    links = curated_links + _auto_links(events, curated_links)
    if projection and projection_sources:
        for source in projection_sources[-3:]:
            links.append(
                {
                    "source": source["id"],
                    "target": projection["id"],
                    "kind": "forecast_projection_source",
                    "weight": round(projection.get("confidence", 0.2), 4),
                    "evidence_type": "model_projection",
                }
            )

    events.sort(key=lambda event: _date_key(event.get("date", "")))
    links = _enrich_links(links, events)
    observed_dates = [event["date"] for event in events if event.get("observed") and _parse_iso_date(event.get("date", ""))]
    all_dates = [event["date"] for event in events if _parse_iso_date(event.get("date", ""))]
    layer_counts = {
        "historical": sum(1 for event in events if event.get("temporal_state") == "historical"),
        "news": sum(1 for event in events if event.get("temporal_state") == "news"),
        "projected": sum(1 for event in events if event.get("temporal_state") == "projected"),
    }
    scenario_deltas = _scenario_deltas(baseline, corrected)
    correction_strength = (
        "strong"
        if news_filter.get("source_count", 0) >= 3
        and news_filter.get("coordinate_count", 0) >= 2
        and not news_filter.get("flags")
        else "weak"
    )
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "input_text": input_text,
        "horizon": horizon,
        "map_projection": "EPSG:3857_web_mercator",
        "events": events,
        "links": links,
        "graph": {
            "event_count": len(events),
            "link_count": len(links),
            "layer_counts": layer_counts,
            "curated_link_count": sum(1 for link in links if link.get("evidence_type") == "curated"),
            "inferred_link_count": sum(1 for link in links if link.get("evidence_type") == "inferred_tag_overlap"),
            "projection_link_count": sum(1 for link in links if link.get("evidence_type") == "model_projection"),
        },
        "temporal_bounds": {
            "start": min(all_dates) if all_dates else "",
            "end": max(all_dates) if all_dates else "",
            "observed_end": max(observed_dates) if observed_dates else "",
        },
        "timeline": [
            {
                "date": event["date"],
                "id": event["id"],
                "title": event["title"],
                "location": event["location"],
                "type": event["type"],
                "projected": event["projected"],
            }
            for event in events
        ],
        "news_filter": news_filter,
        "forecast_correction": {
            "baseline": baseline.get("forecast") or {},
            "corrected": corrected.get("forecast") or {},
            "scenario_deltas": scenario_deltas,
            "correction_strength": correction_strength,
            "max_absolute_shift": round(max((abs(value) for value in scenario_deltas.values()), default=0.0), 4),
            "basis": {
                "news_source_count": news_filter.get("source_count", 0),
                "source_coordinate_count": news_filter.get("coordinate_count", 0),
                "source_ratings": news_filter.get("ratings") or {},
            },
        },
        "warnings": [
            "historical_events_are_observed_coordinates",
            "future_projection_nodes_are_not_observed_events",
            "news_correction_requires_source_diversity",
        ]
        + list(news_filter.get("flags") or []),
    }


__all__ = [
    "SCHEMA_VERSION",
    "build_geo_timeline",
    "extract_news_geo_events",
    "load_geo_events",
]
