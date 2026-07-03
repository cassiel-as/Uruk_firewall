"""Task-aware routing policy for local Ollama models.

Local models are workers, not final authorities. This module keeps that
boundary explicit while assigning each bounded task to the most suitable
configured profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import httpx

from services.protocol_concepts import is_protocol_concept_query
from services.task_profiles import get_task_profile, load_task_profiles


DETERMINISTIC_TASKS = frozenset({"extract_json", "normalize_json"})

LOCAL_TASK_PROFILES: dict[str, str] = {
    "classify": "local_classifier",
    "answer_simple": "local_language",
    "summarize": "local_language",
    "compress_context": "local_language",
    "extract_entities": "local_language",
    "rewrite_query": "local_language",
    "protocol_candidate": "local_protocol_candidate",
    "upgrade_audit_candidate": "local_protocol_candidate",
    "vision_describe": "vision",
}

LOCAL_ONLY_BOUNDARIES = frozenset({
    "deep_reasoning",
    "final_answer",
    "protocol_decision",
    "safety_decision",
    "tool_authorization",
    "system_change",
    "current_events",
})

ESCALATION_PROFILES: dict[str, str] = {
    "deep_reasoning": "deep_reasoning",
    "code_change": "code_coworker",
    "system_change": "upgrade",
    "tool_design": "tool_design",
    "security_review": "review",
    "windows_context": "windows_copilot",
}


@dataclass(frozen=True)
class LocalModelDecision:
    task: str
    execution: str
    profile_name: str = ""
    provider: str = ""
    model: str = ""
    authority: str = "worker"
    reason: str = ""
    escalation_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "execution": self.execution,
            "profile": self.profile_name,
            "provider": self.provider,
            "model": self.model,
            "authority": self.authority,
            "reason": self.reason,
            "escalation_required": self.escalation_required,
        }


def select_local_model(
    task: str,
    text: str = "",
    *,
    config_dir: str | Path = "config",
    requested_profile: str = "auto",
) -> LocalModelDecision:
    """Return the bounded execution policy for one task."""
    task = str(task or "").strip().lower()
    requested_profile = str(requested_profile or "auto").strip()

    if task in DETERMINISTIC_TASKS:
        return LocalModelDecision(
            task=task,
            execution="deterministic",
            authority="deterministic",
            reason="Structured parsing is more reliable without a model.",
        )

    if task in LOCAL_ONLY_BOUNDARIES:
        return LocalModelDecision(
            task=task,
            execution="escalate",
            authority="none",
            reason="Task requires reasoning, authority, or fresh external evidence.",
            escalation_required=True,
        )

    if task == "answer_simple" and is_protocol_concept_query(text):
        return LocalModelDecision(
            task=task,
            execution="escalate",
            authority="none",
            reason="Protocol concept questions require the full pipeline with knowledge and Trinity.",
            escalation_required=True,
        )

    profile_name = (
        requested_profile
        if requested_profile not in {"", "auto", "small"}
        else LOCAL_TASK_PROFILES.get(task, "local_language")
    )
    profile = get_task_profile(profile_name, config_dir)
    authority = str(profile.get("authority") or "worker")
    return LocalModelDecision(
        task=task,
        execution="local_model",
        profile_name=profile_name,
        provider=str(profile.get("provider") or ""),
        model=str(profile.get("model") or ""),
        authority=authority,
        reason=f"Bounded {task} task assigned to {profile_name}.",
        escalation_required=False,
    )


async def effective_timeout(profile: Mapping[str, Any]) -> float:
    """Use a larger timeout when an Ollama model is not already loaded."""
    warm_timeout = float(profile.get("timeout_seconds") or 15.0)
    cold_timeout = float(profile.get("cold_start_timeout_seconds") or warm_timeout)
    if str(profile.get("provider") or "").casefold() != "ollama":
        return warm_timeout

    api_base = str(profile.get("api_base") or "http://localhost:11434").rstrip("/")
    target = str(profile.get("model") or "")
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(f"{api_base}/api/ps")
            response.raise_for_status()
            loaded = {
                str(item.get("name") or item.get("model") or "")
                for item in (response.json().get("models") or [])
            }
        return warm_timeout if target in loaded else cold_timeout
    except Exception:
        return cold_timeout


async def routing_status(config_dir: str | Path = "config") -> dict[str, Any]:
    """Expose configured task assignments and currently installed Ollama models."""
    profiles = load_task_profiles(config_dir)
    installed: list[str] = []
    loaded: list[str] = []
    error = ""
    local_profile = profiles.get("local_classifier") or profiles.get("small") or {}
    api_base = str(local_profile.get("api_base") or "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(f"{api_base}/api/tags")
            response.raise_for_status()
            installed = [
                str(item.get("name") or item.get("model") or "")
                for item in (response.json().get("models") or [])
            ]
            process_response = await client.get(f"{api_base}/api/ps")
            process_response.raise_for_status()
            loaded = [
                str(item.get("name") or item.get("model") or "")
                for item in (process_response.json().get("models") or [])
            ]
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    routes = {}
    for task, profile_name in LOCAL_TASK_PROFILES.items():
        profile = profiles.get(profile_name) or {}
        model = str(profile.get("model") or "")
        routes[task] = {
            "execution": "local_model",
            "profile": profile_name,
            "provider": profile.get("provider"),
            "model": model,
            "authority": profile.get("authority") or "worker",
            "installed": model in installed if installed else None,
            "loaded": model in loaded if installed else None,
            "context_window": profile.get("context_window"),
            "timeout_seconds": profile.get("timeout_seconds"),
            "cold_start_timeout_seconds": profile.get("cold_start_timeout_seconds"),
            "effective_timeout_seconds": (
                profile.get("timeout_seconds")
                if model in loaded
                else profile.get("cold_start_timeout_seconds")
            ),
        }

    escalations = {}
    for task, profile_name in ESCALATION_PROFILES.items():
        profile = profiles.get(profile_name) or {}
        escalations[task] = {
            "execution": "large_model_or_desktop",
            "profile": profile_name,
            "provider": profile.get("provider"),
            "model": profile.get("model"),
            "authority": "reviewed_or_pipeline",
        }

    return {
        "policy": "local_models_are_bounded_workers",
        "installed_models": installed,
        "loaded_models": loaded,
        "probe_error": error or None,
        "deterministic_tasks": sorted(DETERMINISTIC_TASKS),
        "large_model_only_tasks": sorted(LOCAL_ONLY_BOUNDARIES),
        "routes": routes,
        "escalation_routes": escalations,
    }
