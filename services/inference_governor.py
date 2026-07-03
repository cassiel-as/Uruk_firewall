"""Per-request model-call budget and actual inference telemetry."""
from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar


T = TypeVar("T")

_SESSION: contextvars.ContextVar[Optional["InferenceSession"]] = contextvars.ContextVar(
    "uruk_inference_session", default=None
)
_CALL_META: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar(
    "uruk_inference_call_meta", default={}
)
_CALL_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "uruk_inference_call_depth", default=0
)


class InferenceBudgetExceeded(RuntimeError):
    """Raised before a model request when the request-level hard cap is reached."""


@dataclass
class InferencePolicy:
    preference: str = "auto"
    route_kind: str = "unknown"
    pipeline_mode: str = "auto"
    planned_calls: int = 8
    hard_max_calls: int = 12
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preference": self.preference,
            "route_kind": self.route_kind,
            "pipeline_mode": self.pipeline_mode,
            "planned_calls": self.planned_calls,
            "hard_max_calls": self.hard_max_calls,
            "reason": self.reason,
        }


@dataclass
class InferenceSession:
    policy: InferencePolicy
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    blocked: int = 0
    calls: list[Dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> Dict[str, Any]:
        unique = sorted(
            {
                f"{item.get('provider', '?')}/{item.get('model', '?')}"
                for item in self.calls
                if item.get("provider") or item.get("model")
            }
        )
        channels: Dict[str, int] = {}
        total_latency = 0.0
        for item in self.calls:
            channel = str(item.get("channel") or "unknown")
            channels[channel] = channels.get(channel, 0) + 1
            total_latency += float(item.get("latency_ms") or 0.0)
        return {
            "schema_version": "uruk_inference_usage.v1",
            "session_id": self.session_id,
            "started_at": self.started_at,
            "policy": self.policy.to_dict(),
            "actual_requests": self.attempted,
            "successful_requests": self.succeeded,
            "failed_requests": self.failed,
            "blocked_requests": self.blocked,
            "remaining_requests": max(0, self.policy.hard_max_calls - self.attempted),
            "unique_model_count": len(unique),
            "unique_models": unique,
            "channels": channels,
            "total_model_latency_ms": round(total_latency, 1),
            "calls": list(self.calls[-40:]),
        }


def _pipeline_planned_calls(pipeline_mode: str, estimated_calls: int) -> int:
    mode = str(pipeline_mode or "auto")
    fixed = {
        "kairos_memory_direct": 0,
        "plain_llm": 1,
        "smart_auto": 1,
        "app_relay": 1,
        "tool_workshop": 1,
        "delabel_only": 1,
        "protocol_compact": 2,
        "trinity_only": 4,
        "combined": 4,
    }
    if mode in fixed:
        return fixed[mode]
    if mode in {"firewall", "blackbox", "blackboxlab", "scr", "news", "sovereign"}:
        return 8
    return max(0, int(estimated_calls or 0))


def plan_inference_policy(
    *,
    preference: str = "auto",
    route_kind: str = "unknown",
    pipeline_mode: str = "auto",
    estimated_calls: int = 8,
    reason: str = "",
) -> InferencePolicy:
    """Compile a hard request cap from route/pipeline intent.

    Planned calls represent the intended logical path. The preference controls
    retry/failover headroom without silently removing required Trinity stages.
    """
    preference = preference if preference in {"auto", "economy", "balanced", "deep"} else "auto"
    planned = _pipeline_planned_calls(pipeline_mode, estimated_calls)
    if route_kind.startswith("deterministic"):
        planned = 0
    elif pipeline_mode in {"", "auto", None}:
        # Auto always executes Stage 1-3 + dispatcher + the 4-node Trinity (8 calls),
        # regardless of route_kind. Budget for that full path so the hard cap never
        # silently errors the Trinity nodes. (small_task previously capped this at 2
        # → "Inference budget exhausted: 4/4" on father/son/spirit/council once any
        # failover retry ate into the tiny budget. Cost-saving for trivial queries
        # must come from a genuinely shorter pipeline_mode such as smart_auto /
        # plain_llm — NOT from starving the auto budget mid-Trinity.)
        planned = 8

    reserve = {
        "economy": 0,
        "balanced": 2,
        "deep": 6,
        "auto": 2 if planned <= 4 else 4,
    }[preference]
    hard_max = planned + reserve
    if planned == 0:
        hard_max = 0
    return InferencePolicy(
        preference=preference,
        route_kind=str(route_kind or "unknown"),
        pipeline_mode=str(pipeline_mode or "auto"),
        planned_calls=planned,
        hard_max_calls=hard_max,
        reason=reason or f"{route_kind}/{pipeline_mode}",
    )


def begin_inference_session(policy: InferencePolicy):
    return _SESSION.set(InferenceSession(policy=policy))


def reset_inference_session(token) -> None:
    _SESSION.reset(token)


def current_inference_session() -> Optional[InferenceSession]:
    return _SESSION.get()


def inference_snapshot() -> Dict[str, Any]:
    session = _SESSION.get()
    if session is None:
        return {
            "schema_version": "uruk_inference_usage.v1",
            "active": False,
            "actual_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "blocked_requests": 0,
            "unique_model_count": 0,
            "unique_models": [],
            "calls": [],
        }
    return {"active": True, **session.snapshot()}


def update_inference_policy(policy: InferencePolicy) -> None:
    session = _SESSION.get()
    if session is not None:
        session.policy = policy


@contextmanager
def model_call_scope(*, role: str = "", provider: str = "", model: str = "", profile: str = ""):
    existing = dict(_CALL_META.get() or {})
    merged = {
        **existing,
        **{k: v for k, v in {
            "role": role,
            "provider": provider,
            "model": model,
            "profile": profile,
        }.items() if v},
    }
    token = _CALL_META.set(merged)
    try:
        yield
    finally:
        _CALL_META.reset(token)


def _channel(provider: str) -> str:
    value = (provider or "").casefold()
    if value == "ollama" or "local" in value:
        return "local"
    if any(term in value for term in ("desktop", "relay", "codex", "claude_code", "copilot", "chatgpt")):
        return "desktop"
    return "api"


async def execute_model_call(
    call: Callable[[], Awaitable[T]],
    *,
    role: str = "",
    provider: str = "",
    model: str = "",
    profile: str = "",
) -> T:
    """Execute and record one real model request.

    Nested wrappers do not double count. Outside a request inference session,
    calls run normally without enforcement or telemetry.
    """
    depth = _CALL_DEPTH.get()
    if depth > 0:
        return await call()

    session = _SESSION.get()
    meta = dict(_CALL_META.get() or {})
    role = role or meta.get("role") or "unscoped"
    provider = provider or meta.get("provider") or "unknown"
    model = model or meta.get("model") or "unknown"
    profile = profile or meta.get("profile") or ""

    if session is not None and session.attempted >= session.policy.hard_max_calls:
        session.blocked += 1
        raise InferenceBudgetExceeded(
            f"Inference budget exhausted: {session.attempted}/"
            f"{session.policy.hard_max_calls} requests used "
            f"({session.policy.preference}, {session.policy.route_kind})."
        )

    call_id = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    if session is not None:
        session.attempted += 1
    depth_token = _CALL_DEPTH.set(depth + 1)
    try:
        result = await call()
    except Exception as exc:
        if session is not None:
            session.failed += 1
            session.calls.append({
                "id": call_id,
                "role": role,
                "provider": provider,
                "model": model,
                "profile": profile,
                "channel": _channel(provider),
                "status": "failed",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            })
        raise
    else:
        if session is not None:
            session.succeeded += 1
            session.calls.append({
                "id": call_id,
                "role": role,
                "provider": provider,
                "model": model,
                "profile": profile,
                "channel": _channel(provider),
                "status": "success",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            })
        return result
    finally:
        _CALL_DEPTH.reset(depth_token)
