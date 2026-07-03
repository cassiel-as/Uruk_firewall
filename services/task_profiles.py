"""
Task profile loader for low-token routing.

Profiles describe which backend should handle a class of work.  They are kept
separate from Trinity node profiles because pre-gate, smart_auto, vision, and
desktop relays are not always full pipeline nodes.
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml


DEFAULT_TASK_PROFILES: dict[str, dict[str, Any]] = {
    "small": {
        "provider": "ollama",
        "model": "qwen2.5:3b",
        "api_base": "http://localhost:11434",
        "api_key_env": "",
        "max_tokens": 512,
        "context_window": 4096,
        "timeout_seconds": 12.0,
        "cold_start_timeout_seconds": 35.0,
        "temperature": 0.1,
        "think": False,
        "keep_alive": "30m",
        "authority": "worker",
    },
    "local_classifier": {
        "provider": "ollama",
        "model": "qwen2.5:3b",
        "api_base": "http://localhost:11434",
        "api_key_env": "",
        "max_tokens": 128,
        "context_window": 2048,
        "timeout_seconds": 12.0,
        "cold_start_timeout_seconds": 35.0,
        "temperature": 0.0,
        "think": False,
        "keep_alive": "30m",
        "authority": "routing_only",
    },
    "local_language": {
        "provider": "ollama",
        "model": "qwen3.5:4b",
        "api_base": "http://localhost:11434",
        "api_key_env": "",
        "max_tokens": 512,
        "context_window": 8192,
        "timeout_seconds": 25.0,
        "cold_start_timeout_seconds": 70.0,
        "temperature": 0.1,
        "think": False,
        "keep_alive": "30m",
        "authority": "worker",
    },
    "local_protocol_candidate": {
        "provider": "ollama",
        "model": "uruk-v762:latest",
        "api_base": "http://localhost:11434",
        "api_key_env": "",
        "max_tokens": 512,
        "context_window": 8192,
        "timeout_seconds": 30.0,
        "cold_start_timeout_seconds": 70.0,
        "temperature": 0.2,
        "think": False,
        "keep_alive": "15m",
        "authority": "candidate_only",
    },
    "vision": {
        "provider": "ollama",
        "model": "qwen3-vl:4b",
        "api_base": "http://localhost:11434",
        "api_key_env": "",
        "max_tokens": 512,
        "context_window": 8192,
        "timeout_seconds": 60.0,
        "cold_start_timeout_seconds": 150.0,
        "temperature": 0.1,
        "think": False,
        "keep_alive": "15m",
        "authority": "observation_only",
    },
    "code_coworker": {
        "provider": "codex_desktop",
        "model": "codex",
        "api_base": "app://codex",
        "api_key_env": "",
        "max_tokens": 4096,
        "timeout_seconds": 180.0,
    },
    "upgrade": {
        "provider": "codex_desktop",
        "model": "codex",
        "api_base": "app://codex",
        "api_key_env": "",
        "max_tokens": 4096,
        "timeout_seconds": 180.0,
    },
    "tool_design": {
        "provider": "codex_desktop",
        "model": "codex",
        "api_base": "app://codex",
        "api_key_env": "",
        "max_tokens": 4096,
        "timeout_seconds": 180.0,
    },
    "review": {
        "provider": "codex_desktop",
        "model": "codex",
        "api_base": "app://codex",
        "api_key_env": "",
        "max_tokens": 4096,
        "timeout_seconds": 180.0,
    },
    "deep_reasoning": {
        "provider": "claude_desktop",
        "model": "claude_desktop",
        "api_base": "app://claude",
        "api_key_env": "",
        "max_tokens": 4096,
        "timeout_seconds": 180.0,
    },
    "windows_copilot": {
        "provider": "copilot_desktop",
        "model": "copilot",
        "api_base": "app://copilot",
        "api_key_env": "",
        "max_tokens": 2048,
        "timeout_seconds": 180.0,
    },
    "api_reasoning": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "api_base": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "max_tokens": 4096,
        "timeout_seconds": 90.0,
    },
}

_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _config_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / "nodes.yaml"


def _coerce_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 64000) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        ivalue = default
    return max(minimum, min(maximum, ivalue))


def _coerce_float(value: Any, default: float, *, minimum: float = 0.5, maximum: float = 600.0) -> float:
    try:
        fvalue = float(value)
    except (TypeError, ValueError):
        fvalue = default
    return max(minimum, min(maximum, fvalue))


def _coerce_temperature(value: Any, default: float = 0.2) -> float:
    try:
        fvalue = float(value)
    except (TypeError, ValueError):
        fvalue = default
    return max(0.0, min(2.0, fvalue))


def normalize_task_profile(
    name: str,
    spec: Optional[Mapping[str, Any]],
    defaults: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    base = dict(defaults or DEFAULT_TASK_PROFILES.get(name, {}))
    raw = dict(spec or {})

    provider = str(raw.get("provider", base.get("provider", "")) or "").strip()
    model = str(raw.get("model", base.get("model", "")) or "").strip()
    api_base = str(raw.get("api_base", base.get("api_base", "")) or "").strip()
    api_key_env = str(raw.get("api_key_env", base.get("api_key_env", "")) or "").strip()

    return {
        "provider": provider,
        "model": model,
        "api_base": api_base,
        "api_key_env": api_key_env,
        "max_tokens": _coerce_int(raw.get("max_tokens", base.get("max_tokens", 2048)), int(base.get("max_tokens", 2048))),
        "context_window": _coerce_int(
            raw.get("context_window", base.get("context_window", 8192)),
            int(base.get("context_window", 8192)),
            minimum=512,
            maximum=262144,
        ),
        "timeout_seconds": _coerce_float(
            raw.get("timeout_seconds", base.get("timeout_seconds", 60.0)),
            float(base.get("timeout_seconds", 60.0)),
        ),
        "cold_start_timeout_seconds": _coerce_float(
            raw.get("cold_start_timeout_seconds", base.get("cold_start_timeout_seconds", 120.0)),
            float(base.get("cold_start_timeout_seconds", 120.0)),
        ),
        "temperature": _coerce_temperature(
            raw.get("temperature", base.get("temperature", 0.2)),
            float(base.get("temperature", 0.2)),
        ),
        "think": bool(raw.get("think", base.get("think", False))),
        "keep_alive": str(raw.get("keep_alive", base.get("keep_alive", "15m")) or "15m"),
        "authority": str(raw.get("authority", base.get("authority", "worker")) or "worker"),
    }


def merge_task_profiles(raw_profiles: Optional[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    merged = deepcopy(DEFAULT_TASK_PROFILES)
    if isinstance(raw_profiles, Mapping):
        for name, spec in raw_profiles.items():
            if not isinstance(name, str) or not isinstance(spec, Mapping):
                continue
            merged[name] = normalize_task_profile(name, spec, merged.get(name))
    return {name: normalize_task_profile(name, spec, DEFAULT_TASK_PROFILES.get(name)) for name, spec in merged.items()}


def load_task_profiles(config_dir: str | Path = "config") -> dict[str, dict[str, Any]]:
    cfg = _config_path(config_dir)
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    except Exception:
        data = {}
    raw = data.get("task_profiles") if isinstance(data, Mapping) else None
    return merge_task_profiles(raw if isinstance(raw, Mapping) else None)


def get_task_profile(name: str, config_dir: str | Path = "config") -> dict[str, Any]:
    profiles = load_task_profiles(config_dir)
    return profiles.get(name) or normalize_task_profile(name, None)


def profile_api_key(profile: Mapping[str, Any]) -> str:
    env_name = str(profile.get("api_key_env") or "").strip()
    return os.environ.get(env_name, "") if env_name else ""


def validate_task_profiles_payload(
    profiles: Optional[Mapping[str, Any]],
    valid_providers: Optional[set[str]] = None,
) -> Optional[str]:
    if profiles is None:
        return None
    if not isinstance(profiles, Mapping):
        return "task_profiles must be dict"

    for name, spec in profiles.items():
        if not isinstance(name, str) or not _PROFILE_NAME_RE.match(name):
            return f"task profile name {name!r}: alnum/underscore/dash only"
        if not isinstance(spec, Mapping):
            return f"task profile {name}: spec must be dict"

        provider = str(spec.get("provider") or "").strip()
        if provider and valid_providers and provider not in valid_providers:
            return f"task profile {name}: invalid provider {provider!r}"

        api_base = str(spec.get("api_base") or "").strip()
        if api_base and not (
            api_base.startswith("http://")
            or api_base.startswith("https://")
            or api_base.startswith("app://")
        ):
            return f"task profile {name}: api_base must start with http://, https://, or app://"

        api_key_env = str(spec.get("api_key_env") or "").strip()
        if api_key_env and not api_key_env.replace("_", "").isalnum():
            return f"task profile {name}: api_key_env must be alnum/underscore only"

        if "max_tokens" in spec:
            try:
                max_tokens = int(spec.get("max_tokens"))
            except (TypeError, ValueError):
                return f"task profile {name}: max_tokens must be integer"
            if not (1 <= max_tokens <= 64000):
                return f"task profile {name}: max_tokens out of range [1, 64000]"

        if "context_window" in spec:
            try:
                context_window = int(spec.get("context_window"))
            except (TypeError, ValueError):
                return f"task profile {name}: context_window must be integer"
            if not (512 <= context_window <= 262144):
                return f"task profile {name}: context_window out of range [512, 262144]"

        if "timeout_seconds" in spec:
            try:
                timeout = float(spec.get("timeout_seconds"))
            except (TypeError, ValueError):
                return f"task profile {name}: timeout_seconds must be number"
            if not (0.5 <= timeout <= 600):
                return f"task profile {name}: timeout_seconds out of range [0.5, 600]"

        if "cold_start_timeout_seconds" in spec:
            try:
                cold_timeout = float(spec.get("cold_start_timeout_seconds"))
            except (TypeError, ValueError):
                return f"task profile {name}: cold_start_timeout_seconds must be number"
            if not (0.5 <= cold_timeout <= 600):
                return f"task profile {name}: cold_start_timeout_seconds out of range [0.5, 600]"

        if "temperature" in spec:
            try:
                temperature = float(spec.get("temperature"))
            except (TypeError, ValueError):
                return f"task profile {name}: temperature must be number"
            if not (0.0 <= temperature <= 2.0):
                return f"task profile {name}: temperature out of range [0, 2]"

    return None
