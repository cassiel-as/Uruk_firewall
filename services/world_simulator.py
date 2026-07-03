"""Deterministic world-state simulator for URUK.

This module turns vessel state, tools, memories, and a user query into a small
graph that the UI can render.  It does not call an LLM.  The goal is to make
Coordinate Theory concepts inspectable as entities, relations, forces, and
scenario deltas before the main model explains them.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APP_ROOT / "data"


_ABSTRACT_TERMS = {
    "自由": "freedom",
    "責任": "responsibility",
    "权力": "power",
    "權力": "power",
    "控制": "control",
    "信任": "trust",
    "恐懼": "fear",
    "代價": "cost",
    "風險": "risk",
    "黑箱": "blackbox",
    "熵": "entropy",
    "座標": "coordinate",
    "格式化": "formatting",
    "主權": "sovereignty",
    "freedom": "freedom",
    "responsibility": "responsibility",
    "power": "power",
    "control": "control",
    "trust": "trust",
    "fear": "fear",
    "cost": "cost",
    "risk": "risk",
    "blackbox": "blackbox",
    "entropy": "entropy",
    "coordinate": "coordinate",
    "formatting": "formatting",
    "sovereignty": "sovereignty",
}

_ACTION_TERMS = ("應唔應該", "如果", "會點", "推演", "simulate", "scenario", "should i", "what if")
_WORLD_TERMS = ("新聞", "戰爭", "制度", "公司", "政府", "平台", "學校", "市場", "policy", "war", "state", "platform")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, text: str) -> str:
    digest = hashlib.sha1((text or prefix).encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _coord(seed: str, radius: float = 6.0) -> Dict[str, float]:
    digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).digest()
    a = int.from_bytes(digest[:4], "big") / 2**32 * math.tau
    b = int.from_bytes(digest[4:8], "big") / 2**32 * math.tau
    r = radius * (0.45 + (digest[8] / 255) * 0.55)
    return {
        "x": round(math.cos(a) * r, 3),
        "y": round(math.sin(a) * r, 3),
        "z": round(math.sin(b) * radius * 0.75, 3),
    }


def _entity(
    entity_id: str,
    label: str,
    kind: str,
    *,
    role: str = "",
    weight: float = 1.0,
    position: Optional[Dict[str, float]] = None,
    notes: Optional[List[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "id": entity_id,
        "label": label[:80],
        "kind": kind,
        "role": role,
        "weight": round(max(0.1, min(float(weight or 1.0), 5.0)), 3),
        "position": position or _coord(entity_id),
        "notes": [n for n in (notes or []) if n][:5],
        "meta": meta or {},
    }


def _relation(source: str, target: str, kind: str, *, weight: float = 1.0, label: str = "") -> Dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "kind": kind,
        "weight": round(max(0.1, min(float(weight or 1.0), 5.0)), 3),
        "label": label or kind,
    }


def _detect_terms(text: str) -> List[str]:
    lower = (text or "").lower()
    found: List[str] = []
    for term, canonical in _ABSTRACT_TERMS.items():
        if term.lower() in lower and canonical not in found:
            found.append(canonical)
    return found


def should_trigger_world(text: str) -> Dict[str, Any]:
    """Return deterministic routing advice for world simulation."""
    raw = text or ""
    lower = raw.lower().strip()
    explicit = lower.startswith(("/world", "/simulate", "/map", "/scenario", "/coordinate"))
    terms = _detect_terms(raw)
    action_like = any(t in lower for t in _ACTION_TERMS)
    world_like = any(t in lower for t in _WORLD_TERMS)
    should = explicit or bool(terms) or action_like or world_like
    return {
        "should_trigger": should,
        # Abstract terms may warm/update the world model in the background, but
        # only an explicit slash command may replace the main chat response.
        "intercept_chat": explicit,
        "explicit": explicit,
        "terms": terms,
        "reason": (
            "explicit_world_command"
            if explicit
            else "abstract_concept"
            if terms
            else "world_or_action_language"
            if should
            else "not_needed"
        ),
    }


def _load_vessel_state(data_dir: Path) -> Dict[str, Any]:
    try:
        from services.vessel_state import load_state

        return load_state(data_dir)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _load_vessel_profile() -> Dict[str, Any]:
    try:
        from services.vessel_context import summarize_vessel

        return summarize_vessel()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _tool_names(tool_names: Optional[Iterable[str]] = None) -> List[str]:
    if tool_names is not None:
        return sorted({str(t) for t in tool_names if t})
    try:
        from services.computer_tools import TOOL_REGISTRY

        return sorted(TOOL_REGISTRY.keys())
    except Exception:
        return []


def _extract_claim_entities(text: str) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    if not text:
        return entities
    patterns = [
        r"\baccording to\s+([A-Z][^,.;\n]{2,60})",
        r"([A-Z][^,.;\n]{2,60})\s+(?:said|claimed|argued|warned|announced|stated)\b",
    ]
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            entities.append(
                _entity(
                    _stable_id("speaker", name),
                    name,
                    "speaker",
                    role="claim_origin",
                    weight=1.2,
                    notes=["possible claim origin extracted from input"],
                )
            )
    return entities[:6]


def build_world_state(
    *,
    input_text: str = "",
    data_dir: Optional[Path] = None,
    tool_names: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Build the current world graph without running scenario deltas."""
    root = Path(data_dir) if data_dir else DATA_DIR
    vessel_state = _load_vessel_state(root)
    vessel_profile = _load_vessel_profile()
    tools = _tool_names(tool_names)
    terms = _detect_terms(input_text)

    entities: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []

    entities.append(
        _entity(
            "operator",
            "Operator / Cassiel_as",
            "operator",
            role="origin_coordinate",
            weight=2.2,
            position={"x": 0.0, "y": 0.0, "z": 0.0},
            notes=["physical origin anchor: 2019-06-12"],
        )
    )
    entities.append(
        _entity(
            "vessel",
            "URUK protocol carrier",
            "vessel",
            role="runtime_body",
            weight=2.0,
            position={"x": 1.4, "y": -0.8, "z": 0.7},
            notes=[
                f"{len(vessel_profile.get('capabilities') or [])} capabilities",
                f"vessel_id={vessel_profile.get('vessel_id', 'unknown')}",
            ],
            meta={"profile": vessel_profile},
        )
    )
    relations.append(_relation("operator", "vessel", "inhabits", weight=2.0, label="runs through"))

    location = vessel_state.get("location") if isinstance(vessel_state, dict) else None
    if isinstance(location, dict):
        loc_label = location.get("label") or "current location"
        loc_id = "location_current"
        entities.append(
            _entity(
                loc_id,
                loc_label,
                "location",
                role="spatial_anchor",
                weight=1.3,
                position={"x": -1.6, "y": -1.2, "z": 0.2},
                notes=[f"{location.get('lat')}, {location.get('lon')}"],
                meta={"location": location},
            )
        )
        relations.append(_relation("vessel", loc_id, "located_at", weight=1.2))

    notes = vessel_state.get("notes") if isinstance(vessel_state, dict) else []
    for note in list(notes or [])[:3]:
        nid = _stable_id("note", note.get("id") or note.get("title") or "")
        entities.append(
            _entity(
                nid,
                note.get("title") or "note",
                "note",
                role="self_observation",
                weight=0.8,
                notes=[(note.get("body") or "")[:120]],
                meta={"note_id": note.get("id"), "updated_at": note.get("updated_at")},
            )
        )
        relations.append(_relation("vessel", nid, "records", weight=0.8))

    events = vessel_state.get("calendar_events") if isinstance(vessel_state, dict) else []
    for event in list(events or [])[:3]:
        eid = _stable_id("event", event.get("id") or event.get("title") or "")
        entities.append(
            _entity(
                eid,
                event.get("title") or "event",
                "event",
                role="commitment",
                weight=1.0,
                notes=[event.get("start") or "", event.get("location") or ""],
                meta={"event_id": event.get("id"), "start": event.get("start")},
            )
        )
        relations.append(_relation("operator", eid, "committed_to", weight=1.0))

    entities.append(
        _entity(
            "kairos_active",
            "Kairos active memory",
            "memory",
            role="causal_anchor",
            weight=1.8,
            position={"x": -2.2, "y": 1.8, "z": 1.2},
            notes=["short high-density operator-reviewed memory"],
        )
    )
    relations.append(_relation("operator", "kairos_active", "remembers_through", weight=1.7))

    tool_weight = min(3.0, max(0.5, len(tools) / 30.0))
    entities.append(
        _entity(
            "tool_registry",
            f"Tool registry ({len(tools)})",
            "tool_layer",
            role="action_surface",
            weight=tool_weight,
            position={"x": 2.4, "y": 1.2, "z": -0.4},
            notes=tools[:5],
            meta={"tool_count": len(tools)},
        )
    )
    relations.append(_relation("vessel", "tool_registry", "can_act_through", weight=tool_weight))

    if input_text:
        entities.append(
            _entity(
                "current_query",
                "Current query",
                "query",
                role="world_slice_trigger",
                weight=1.5,
                position={"x": 0.4, "y": 2.6, "z": 0.8},
                notes=[input_text[:180]],
                meta={"detected_terms": terms},
            )
        )
        relations.append(_relation("operator", "current_query", "asks", weight=1.5))
        relations.append(_relation("current_query", "kairos_active", "may_reference", weight=0.7))
        for ent in _extract_claim_entities(input_text):
            entities.append(ent)
            relations.append(_relation(ent["id"], "current_query", "claims_into", weight=1.1))

    if terms:
        for term in terms[:6]:
            tid = f"concept_{term}"
            entities.append(
                _entity(
                    tid,
                    term,
                    "concept",
                    role="coordinate_concept",
                    weight=1.1,
                    notes=[f"detected from input as {term}"],
                )
            )
            relations.append(_relation("current_query", tid, "activates", weight=1.0))

    entities.append(
        _entity(
            "external_formatting",
            "External formatting field",
            "force_field",
            role="replacement_pressure",
            weight=1.3,
            position={"x": 4.2, "y": 0.0, "z": 0.3},
            notes=["represents pressure to replace local coordinates with external labels"],
        )
    )
    entities.append(
        _entity(
            "unknown_blackbox",
            "Unknown / blackbox",
            "blackbox",
            role="unopened_causal_node",
            weight=1.2,
            position={"x": -3.6, "y": -0.2, "z": 1.8},
            notes=["kept visible until evidence opens it"],
        )
    )
    relations.append(_relation("external_formatting", "operator", "pressures", weight=1.0))
    relations.append(_relation("unknown_blackbox", "current_query" if input_text else "operator", "obscures", weight=0.9))

    return {
        "schema_version": "world_state.v1",
        "generated_at": _now(),
        "input_text": input_text,
        "trigger": should_trigger_world(input_text),
        "entities": entities,
        "relations": relations,
        "forces": compute_forces(input_text=input_text, entities=entities, relations=relations),
        "source_counts": {
            "tools": len(tools),
            "notes": len(notes or []),
            "calendar_events": len(events or []),
            "detected_terms": len(terms),
        },
    }


def compute_forces(*, input_text: str, entities: List[Dict[str, Any]], relations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    terms = set(_detect_terms(input_text))
    relation_kinds = {r.get("kind") for r in relations}
    blackboxes = sum(1 for e in entities if e.get("kind") == "blackbox")
    notes = sum(1 for e in entities if e.get("kind") == "note")
    tools = next((e for e in entities if e.get("id") == "tool_registry"), {})
    tool_count = int((tools.get("meta") or {}).get("tool_count") or 0)

    formatting = 0.3 + (0.25 if {"control", "formatting", "power"} & terms else 0.0)
    blackbox_pressure = min(1.0, 0.25 + blackboxes * 0.2 + (0.25 if "blackbox" in terms else 0.0))
    negative_entropy = min(1.0, 0.25 + notes * 0.08 + min(tool_count, 80) / 160.0)
    cost_visibility = 0.35 + (0.3 if {"cost", "risk", "responsibility"} & terms else 0.0)
    coordinate_integrity = max(0.0, min(1.0, 0.45 + negative_entropy * 0.35 - formatting * 0.15))

    return [
        {"id": "formatting_pressure", "label": "formatting pressure", "value": round(formatting, 3), "direction": "external_to_operator"},
        {"id": "blackbox_pressure", "label": "blackbox pressure", "value": round(blackbox_pressure, 3), "direction": "unknown_to_query"},
        {"id": "negative_entropy_input", "label": "negative entropy input", "value": round(negative_entropy, 3), "direction": "tools_memory_to_vessel"},
        {"id": "cost_visibility", "label": "cost visibility", "value": round(min(1.0, cost_visibility), 3), "direction": "query_to_carriers"},
        {"id": "coordinate_integrity", "label": "coordinate integrity", "value": round(coordinate_integrity, 3), "direction": "operator_anchor"},
        {"id": "relation_density", "label": "relation density", "value": round(min(1.0, len(relation_kinds) / 8.0), 3), "direction": "graph"},
    ]


def simulate_world(
    *,
    input_text: str = "",
    horizon: str = "short",
    data_dir: Optional[Path] = None,
    tool_names: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    state = build_world_state(input_text=input_text, data_dir=data_dir, tool_names=tool_names)
    forces = {f["id"]: f["value"] for f in state.get("forces", [])}
    trigger = state.get("trigger") or {}
    terms = trigger.get("terms") or []

    base_integrity = float(forces.get("coordinate_integrity", 0.5))
    formatting = float(forces.get("formatting_pressure", 0.3))
    blackbox = float(forces.get("blackbox_pressure", 0.3))
    cost_visibility = float(forces.get("cost_visibility", 0.35))

    scenarios = [
        {
            "id": "maintain_coordinate",
            "label": "維持自身座標",
            "summary": "保留本地座標，先問代價承擔者同黑箱來源，再輸出結論。",
            "delta": {
                "coordinate_integrity": round(0.18 + cost_visibility * 0.12, 3),
                "formatting_pressure": round(-0.08, 3),
                "blackbox_pressure": round(-0.05, 3),
            },
            "risk": "medium" if formatting > 0.55 else "low",
        },
        {
            "id": "accept_external_frame",
            "label": "接受外部框架",
            "summary": "直接沿用外部問題格式，速度快，但容易遮蔽承擔者。",
            "delta": {
                "coordinate_integrity": round(-0.2 - formatting * 0.1, 3),
                "formatting_pressure": round(0.12, 3),
                "blackbox_pressure": round(0.08, 3),
            },
            "risk": "high" if formatting > 0.45 or blackbox > 0.45 else "medium",
        },
        {
            "id": "open_blackbox",
            "label": "先打開黑箱",
            "summary": "把未知來源、權力位置、資料缺口顯性化；慢一點，但降低錯判。",
            "delta": {
                "coordinate_integrity": round(0.1, 3),
                "formatting_pressure": round(-0.03, 3),
                "blackbox_pressure": round(-0.22 - blackbox * 0.12, 3),
            },
            "risk": "low",
        },
    ]

    best = max(
        scenarios,
        key=lambda s: s["delta"].get("coordinate_integrity", 0) - max(0, s["delta"].get("blackbox_pressure", 0)),
    )
    evaluation = {
        "recommended_scenario": best["id"],
        "needs_world_view": bool(trigger.get("should_trigger") or terms),
        "detected_terms": terms,
        "horizon": horizon,
        "summary": (
            "World simulation 建議先打開黑箱，再維持自身座標。"
            if best["id"] == "open_blackbox"
            else f"World simulation 建議：{best['label']}。"
        ),
        "warnings": [
            "simulation is deterministic and heuristic; LLM should explain, not override, the graph",
            "3D view is a visualization of state, not proof by itself",
        ],
        "scores": {
            "base_coordinate_integrity": round(base_integrity, 3),
            "formatting_pressure": round(formatting, 3),
            "blackbox_pressure": round(blackbox, 3),
            "cost_visibility": round(cost_visibility, 3),
        },
    }

    return {
        "ok": True,
        "schema_version": "world_simulation.v1",
        "generated_at": _now(),
        "world": state,
        "scenarios": scenarios,
        "evaluation": evaluation,
    }
