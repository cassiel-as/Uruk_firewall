"""Prompt/API formatting for VesselProfile.

This module keeps hardware identity separate from model identity.  A backend can
be Claude/Codex/OpenRouter; the vessel is the physical runtime that provides
or lacks sensors, actuators, buses, and middleware.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from services.vessel_scanner import VesselProfile, get_vessel_profile, identify_hardware_tool_gaps


def _profile_dict(profile: Optional[VesselProfile | Dict[str, Any]]) -> Dict[str, Any]:
    if profile is None:
        return get_vessel_profile().to_dict()
    if isinstance(profile, VesselProfile):
        return profile.to_dict()
    return dict(profile or {})


def summarize_vessel(profile: Optional[VesselProfile | Dict[str, Any]] = None) -> Dict[str, Any]:
    data = _profile_dict(profile)
    devices = data.get("devices") or []
    by_kind: Dict[str, int] = {}
    for dev in devices:
        if isinstance(dev, dict):
            kind = str(dev.get("kind") or "unknown")
            by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "vessel_id": data.get("vessel_id"),
        "generated_at": data.get("generated_at"),
        "platform": data.get("platform") or {},
        "hardware": data.get("hardware") or {},
        "capabilities": list(data.get("capabilities") or []),
        "device_counts": by_kind,
        "warnings": list(data.get("warnings") or []),
    }


def _format_list(items: Iterable[str], *, limit: int = 10) -> str:
    vals = [str(x) for x in items if str(x)]
    if not vals:
        return "none"
    if len(vals) > limit:
        return ", ".join(vals[:limit]) + f", +{len(vals) - limit} more"
    return ", ".join(vals)


def _device_group_lines(devices: List[Any], *, max_kinds: int = 8, per_kind: int = 4) -> List[str]:
    grouped: Dict[str, List[str]] = {}
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        kind = str(dev.get("kind") or "device")
        name = str(dev.get("path") or dev.get("name") or dev.get("id") or "").strip()
        if not name:
            continue
        bucket = grouped.setdefault(kind, [])
        if name not in bucket:
            bucket.append(name)

    lines: List[str] = []
    for kind in sorted(grouped.keys())[:max_kinds]:
        names = grouped[kind]
        suffix = f", +{len(names) - per_kind} more" if len(names) > per_kind else ""
        lines.append(f"- {kind}: {'; '.join(names[:per_kind])}{suffix}")
    return lines


def _hardware_gap_lines(profile_data: Dict[str, Any], *, limit: int = 6) -> List[str]:
    try:
        from services.computer_tools import TOOL_REGISTRY

        gaps = identify_hardware_tool_gaps(profile_data, TOOL_REGISTRY.keys())
    except Exception:
        gaps = []

    lines: List[str] = []
    for gap in gaps[:limit]:
        if not isinstance(gap, dict):
            continue
        missing = _format_list(gap.get("accepted_tools") or [gap.get("suggested_name")], limit=4)
        lines.append(
            "- "
            f"{gap.get('hardware_capability', 'unknown')}/{gap.get('purpose', 'unknown')} "
            f"missing={missing} "
            f"priority={gap.get('priority', 'unknown')} "
            f"commissioning_required={bool(gap.get('commissioning_required'))}"
        )
    return lines


def vessel_context_block(
    profile: Optional[VesselProfile | Dict[str, Any]] = None,
    *,
    include_state: Optional[bool] = None,
) -> str:
    """Return a compact block safe to inject into system prompts."""
    if include_state is None:
        include_state = profile is None
    data = _profile_dict(profile)
    platform_info = data.get("platform") or {}
    hardware = data.get("hardware") or {}
    devices = data.get("devices") or []
    capabilities = list(data.get("capabilities") or [])
    warnings = list(data.get("warnings") or [])
    state_summary: Dict[str, Any] = {}
    if include_state:
        try:
            from services.vessel_state import context_summary

            state_summary = context_summary()
        except Exception:
            state_summary = {}

    expectation_lines: List[str] = []
    for item in data.get("tool_expectations") or []:
        if not isinstance(item, dict):
            continue
        capability = item.get("capability")
        purpose = item.get("purpose")
        tools = _format_list(item.get("accepted_tools") or [], limit=4)
        expectation_lines.append(f"- {capability}/{purpose}: {tools}")
        if len(expectation_lines) >= 8:
            break
    device_lines = _device_group_lines(devices)
    gap_lines = _hardware_gap_lines(data)

    lines = [
        "━━━ VESSEL PROFILE / Runtime Hardware Identity ━━━",
        f"vessel_id: {data.get('vessel_id', 'unknown')}",
        (
            "runtime_vessel: "
            f"{platform_info.get('system', 'unknown')} "
            f"{platform_info.get('machine', '')}".strip()
        ),
        (
            "compute: "
            f"cpu_count={hardware.get('cpu_count', 'unknown')}, "
            f"ram_bytes={hardware.get('ram_bytes', 'unknown')}, "
            f"gpu_count={hardware.get('gpu_count', 0)}"
        ),
        f"capabilities: {_format_list(capabilities, limit=14)}",
    ]
    if device_lines:
        lines.append("devices_sample_by_kind:")
        lines.extend(device_lines)
    if expectation_lines:
        lines.append("capability_tool_expectations:")
        lines.extend(expectation_lines)
    if gap_lines:
        lines.append("known_hardware_tool_gaps:")
        lines.extend(gap_lines)
    location = state_summary.get("location") or {}
    if location:
        label = location.get("label") or "unlabelled"
        lines.append(
            "current_location: "
            f"{label} ({location.get('lat')}, {location.get('lon')}) "
            f"source={location.get('source', 'unknown')} "
            f"confidence={location.get('confidence', 'unknown')}"
        )
    else:
        lines.append("current_location: none_saved")
    upcoming = state_summary.get("upcoming_events") or []
    if upcoming:
        lines.append("upcoming_commitments:")
        for event in upcoming[:3]:
            lines.append(f"- {event.get('start', '')}: {event.get('title', '')}")
    recent_notes = state_summary.get("recent_notes") or []
    if recent_notes:
        lines.append("recent_self_notes:")
        for note in recent_notes[:3]:
            lines.append(f"- {note.get('title', '')} ({note.get('kind', '')})")
    if warnings:
        lines.append(f"scanner_warnings: {_format_list(warnings, limit=3)}")
    lines.extend([
        "boundary: hardware detection is evidence, not permission.",
        "boundary: actuator, serial, ROS, GPS, and camera tools require commissioning before trusted use.",
        "━━━ END VESSEL PROFILE ━━━",
    ])
    return "\n".join(lines)


def vessel_api_payload(*, refresh: bool = False, tool_names: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    profile = get_vessel_profile(force=refresh)
    payload = {
        "profile": profile.to_dict(),
        "summary": summarize_vessel(profile),
        "context_block": vessel_context_block(profile, include_state=True),
    }
    if tool_names is not None:
        payload["hardware_gaps"] = identify_hardware_tool_gaps(profile, tool_names)
    return payload
