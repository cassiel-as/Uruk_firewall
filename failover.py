"""
Multi-profile failover engine for Trinity Console LLM calls.

Responsibilities:
  - Classify exceptions raised by adapters (httpx.HTTPStatusError, TimeoutException,
    provider-specific quota errors) into failover triggers.
  - Walk a configured chain of API profiles when the primary call hits a
    failover-eligible error.
  - Track per-profile health (success, fail, latency, cooldown) so we can
    short-circuit known-bad profiles for `cooldown_seconds` and surface the
    state to the UI.

Designed to be import-light — only depends on httpx + stdlib.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

import httpx

from services.provider_rate_limiter import provider_rate_limiter


# ─────────────────────────────────────────────────────────────────
# Error classification
# ─────────────────────────────────────────────────────────────────

class FailoverTrigger:
    """String constants identifying why a call failed."""
    NONE       = "none"          # not failover-eligible; re-raise
    HTTP_429   = "http_429"
    HTTP_5XX   = "http_5xx"
    QUOTA      = "quota"
    TIMEOUT    = "timeout"
    NETWORK    = "network"
    # v8.5 — profile misconfig (404 model not found / 400 bad request).
    # Treated as failover-eligible: cool the broken profile and try next.
    # Without this, ONE bad model name in chain (e.g. cerebras 404) crashes
    # the whole pipeline before subsequent good profiles are tried.
    MISCONFIG  = "profile_misconfig"
    # v8.30 p12 — adapter returned HTTP 200 OK but content failed semantic
    # validation (e.g. prompt-echo / no JSON braces / mostly empty). Without
    # this, a model that "successfully" returns garbage burns the primary slot
    # forever and never falls through to a working sibling provider.
    EMPTY_CONTENT = "empty_content"
    NO_KEY     = "no_key"        # synthetic — chain entry skipped (env var missing)
    COOLING    = "cooling_skip"  # synthetic — chain entry in cooldown
    OK         = "ok"            # synthetic — success


class EmptyContentError(RuntimeError):
    """Raised by stage-call wrappers when adapter returns 200 OK but the body
    is semantically empty (no JSON / prompt-echo / under threshold). Picked up
    by classify_error → FailoverTrigger.EMPTY_CONTENT so call_with_failover
    walks to the next provider instead of returning a silent empty fallback."""


ALL_TRIGGERS = {
    FailoverTrigger.HTTP_429,
    FailoverTrigger.HTTP_5XX,
    FailoverTrigger.QUOTA,
    FailoverTrigger.TIMEOUT,
    FailoverTrigger.NETWORK,
    FailoverTrigger.MISCONFIG,
    FailoverTrigger.EMPTY_CONTENT,
}


def classify_error(exc: BaseException) -> str:
    """Map an exception to a FailoverTrigger.* string.

    Returns FailoverTrigger.NONE when the error should NOT trigger failover
    (e.g. JSON decode bug, auth 401, bad request) — caller re-raises.
    """
    # v8.30 p12 — semantic-empty content from a 200-OK provider is a failover
    # trigger (chain should walk to next provider, not return empty fallback).
    if isinstance(exc, EmptyContentError):
        return FailoverTrigger.EMPTY_CONTENT
    if isinstance(exc, asyncio.TimeoutError):
        return FailoverTrigger.TIMEOUT

    # httpx error hierarchy
    if isinstance(exc, httpx.TimeoutException):
        return FailoverTrigger.TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return FailoverTrigger.HTTP_429
        if 500 <= code < 600:
            return FailoverTrigger.HTTP_5XX
        # v8.5 — profile misconfig: model name wrong (404), bad request (400),
        # or payload too large (413). A provider/model that cannot accept the
        # compiled prompt should be isolated instead of retried by every node.
        # Cool this profile and try next chain entry instead of re-raising.
        if code in (400, 404, 413):
            return FailoverTrigger.MISCONFIG
        # Quota-like errors that providers return with non-429 codes
        if code in (401, 402, 403):
            body = ""
            try:
                body = (exc.response.text or "").lower()
            except Exception:  # noqa: BLE001  — defensive only
                pass
            if any(kw in body for kw in (
                "quota", "insufficient", "exhausted", "credit",
                "billing", "balance", "rate limit",
            )):
                return FailoverTrigger.QUOTA
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return FailoverTrigger.NETWORK

    # Gemini adapter raises RuntimeError with raw response on unexpected shape
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        if "desktop relay unavailable" in msg or "app control is windows-only" in msg:
            return FailoverTrigger.NETWORK
        if any(kw in msg for kw in (
            "resource_exhausted", "quota", "rate_limit", "rate limit",
            "permission_denied", "billing",
        )):
            return FailoverTrigger.QUOTA

    return FailoverTrigger.NONE


# ─────────────────────────────────────────────────────────────────
# Profiles + config
# ─────────────────────────────────────────────────────────────────

@dataclass
class ApiProfile:
    """A reusable provider + endpoint + key-env tuple referenced by name.

    `enabled=False` excludes the profile from the failover chain at resolve
    time, even if a valid key is present. Disabled profiles surface in UI
    so operator can toggle without removing config. Backward compat:
    missing `enabled` in yaml is treated as True (see TrinityConsole loader).
    """
    name: str
    provider: str
    api_base: Optional[str] = None
    api_key_env: Optional[str] = None
    default_model: Optional[str] = None
    enabled: bool = True


@dataclass
class FailoverConfig:
    enabled: bool = True
    global_chain: List[str] = field(default_factory=list)
    cooldown_seconds: float = 300.0
    trigger_on: List[str] = field(default_factory=lambda: [
        FailoverTrigger.HTTP_429,
        FailoverTrigger.HTTP_5XX,
        FailoverTrigger.QUOTA,
        FailoverTrigger.TIMEOUT,
        FailoverTrigger.NETWORK,
        FailoverTrigger.MISCONFIG,
        FailoverTrigger.EMPTY_CONTENT,
    ])
    profiles: Dict[str, ApiProfile] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Health tracker
# ─────────────────────────────────────────────────────────────────

@dataclass
class ProfileHealth:
    success: int = 0
    fail: int = 0
    last_latency_ms: float = 0.0
    last_used_at: float = 0.0
    last_error: Optional[str] = None
    last_trigger: Optional[str] = None
    cooldown_until: float = 0.0   # epoch seconds; 0 == not cooling
    failover_count: int = 0       # how often this profile triggered failover
    consecutive_failures: int = 0
    last_success_at: float = 0.0
    latency_ewma_ms: float = 0.0
    effective_cooldown_seconds: float = 0.0

    def is_cooling(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) < self.cooldown_until


class HealthTracker:
    """Per-profile health stats with optional cross-restart persistence."""

    STATE_SCHEMA_VERSION = "uruk_provider_health.v1"
    LATENCY_SENSITIVE_ROLES = {"delabeling", "explanation", "filter", "dispatcher"}
    RELIABILITY_SENSITIVE_ROLES = {"father", "son", "spirit", "council", "blackboxlab", "scr"}
    MIN_ADAPTIVE_OBSERVATIONS = 2

    def __init__(self, cooldown_seconds: float = 300.0, state_path: Optional[Path] = None):
        self.cooldown_seconds = float(cooldown_seconds)
        self._stats: Dict[str, ProfileHealth] = {}
        self.state_path = Path(state_path) if state_path else None
        self.last_load_error: Optional[str] = None
        self.last_persist_error: Optional[str] = None
        self.loaded_at: float = 0.0
        self.saved_at: float = 0.0
        self.load_skipped_profiles: int = 0
        self._load_state()

    def set_cooldown_seconds(self, seconds: float) -> None:
        self.cooldown_seconds = float(seconds)
        self._persist()

    def get(self, profile: str) -> ProfileHealth:
        h = self._stats.get(profile)
        if h is None:
            h = ProfileHealth()
            self._stats[profile] = h
        return h

    def record_success(self, profile: str, latency_ms: float) -> None:
        h = self.get(profile)
        h.success += 1
        h.last_latency_ms = float(latency_ms)
        h.latency_ewma_ms = (
            float(latency_ms)
            if h.latency_ewma_ms <= 0
            else (0.25 * float(latency_ms)) + (0.75 * h.latency_ewma_ms)
        )
        now = time.time()
        h.last_used_at = now
        h.last_success_at = now
        h.last_error = None
        h.last_trigger = FailoverTrigger.OK
        h.consecutive_failures = 0
        self._persist()

    def record_failure(self, profile: str, trigger: str, err_msg: str,
                       cool_down: bool) -> None:
        h = self.get(profile)
        h.fail += 1
        h.last_used_at = time.time()
        h.last_error = err_msg
        h.last_trigger = trigger
        if cool_down:
            h.consecutive_failures += 1
            multiplier = min(4.0, 2.0 ** max(0, h.consecutive_failures - 1))
            h.effective_cooldown_seconds = self.cooldown_seconds * multiplier
            h.cooldown_until = time.time() + h.effective_cooldown_seconds
            h.failover_count += 1
        self._persist()

    def clear_cooldown(self, profile: str) -> None:
        h = self.get(profile)
        h.cooldown_until = 0.0
        h.effective_cooldown_seconds = 0.0
        h.consecutive_failures = 0
        self._persist()

    def reset(self) -> None:
        self._stats.clear()
        self._persist()

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            schema = payload.get("schema_version") if isinstance(payload, dict) else None
            if schema and schema != self.STATE_SCHEMA_VERSION:
                raise ValueError(f"unsupported schema_version: {schema}")
            raw_profiles = payload.get("profiles") if isinstance(payload, dict) else {}
            if not isinstance(raw_profiles, dict):
                raise ValueError("profiles must be an object")
            now = time.time()
            loaded: Dict[str, ProfileHealth] = {}
            skipped = 0
            for name, raw in raw_profiles.items():
                if not isinstance(name, str) or not isinstance(raw, dict):
                    skipped += 1
                    continue
                try:
                    health = ProfileHealth(
                        success=max(0, int(raw.get("success") or 0)),
                        fail=max(0, int(raw.get("fail") or 0)),
                        last_latency_ms=max(0.0, float(raw.get("last_latency_ms") or 0.0)),
                        last_used_at=max(0.0, float(raw.get("last_used_at") or 0.0)),
                        last_error=(str(raw["last_error"])[:1000] if raw.get("last_error") is not None else None),
                        last_trigger=(str(raw["last_trigger"])[:80] if raw.get("last_trigger") is not None else None),
                        cooldown_until=max(0.0, float(raw.get("cooldown_until") or 0.0)),
                        failover_count=max(0, int(raw.get("failover_count") or 0)),
                        consecutive_failures=max(0, int(raw.get("consecutive_failures") or 0)),
                        last_success_at=max(0.0, float(raw.get("last_success_at") or 0.0)),
                        latency_ewma_ms=max(0.0, float(raw.get("latency_ewma_ms") or 0.0)),
                        effective_cooldown_seconds=max(
                            0.0, float(raw.get("effective_cooldown_seconds") or 0.0)
                        ),
                    )
                except (TypeError, ValueError, OverflowError):
                    skipped += 1
                    continue
                if health.cooldown_until <= now:
                    health.cooldown_until = 0.0
                    health.effective_cooldown_seconds = 0.0
                    health.consecutive_failures = 0
                loaded[name] = health
            self._stats = loaded
            self.load_skipped_profiles = skipped
            self.loaded_at = now
            self.saved_at = float(payload.get("saved_at") or 0.0)
            self.last_load_error = None
        except Exception as exc:  # noqa: BLE001 - persistence must never block startup
            self._stats = {}
            self.last_load_error = f"{type(exc).__name__}: {str(exc)[:240]}"

    def _persist(self) -> None:
        if self.state_path is None:
            return
        try:
            now = time.time()
            payload = {
                "schema_version": self.STATE_SCHEMA_VERSION,
                "saved_at": now,
                "cooldown_seconds": self.cooldown_seconds,
                "profiles": {name: asdict(health) for name, health in self._stats.items()},
            }
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.state_path)
            self.saved_at = now
            self.last_persist_error = None
        except Exception as exc:  # noqa: BLE001 - failover must keep operating in memory
            self.last_persist_error = f"{type(exc).__name__}: {str(exc)[:240]}"

    def persistence_status(self) -> Dict[str, object]:
        return {
            "configured": self.state_path is not None,
            "path": str(self.state_path) if self.state_path else None,
            "schema_version": self.STATE_SCHEMA_VERSION,
            "profile_count": len(self._stats),
            "loaded_at": self.loaded_at,
            "loaded_iso": (
                datetime.fromtimestamp(self.loaded_at).isoformat(timespec="seconds")
                if self.loaded_at else None
            ),
            "saved_at": self.saved_at,
            "saved_iso": (
                datetime.fromtimestamp(self.saved_at).isoformat(timespec="seconds")
                if self.saved_at else None
            ),
            "skipped_profiles": self.load_skipped_profiles,
            "load_error": self.last_load_error,
            "persist_error": self.last_persist_error,
        }

    def rank_profiles(
        self,
        profiles: List[ApiProfile],
        *,
        role: str,
        adaptive: bool = True,
    ) -> tuple[List[ApiProfile], Dict[str, object]]:
        """Conservatively rank fallback profiles using persisted health.

        Primary selection is intentionally out of scope. Explicit stage/node
        fallback lists should call this with adaptive=False so operator intent
        remains authoritative. Unproven profiles preserve configured order.
        """
        role = str(role or "unknown")
        if role in self.LATENCY_SENSITIVE_ROLES:
            policy = "latency_sensitive"
            reliability_weight, latency_weight, config_weight = 0.55, 0.35, 0.10
        elif role in self.RELIABILITY_SENSITIVE_ROLES:
            policy = "reliability_sensitive"
            reliability_weight, latency_weight, config_weight = 0.75, 0.15, 0.10
        else:
            policy = "balanced"
            reliability_weight, latency_weight, config_weight = 0.65, 0.25, 0.10

        entries: List[Dict[str, object]] = []
        for index, profile in enumerate(profiles):
            health = self._stats.get(profile.name) or ProfileHealth()
            total = health.success + health.fail
            raw_success_rate = health.success / total if total else None
            smoothed_reliability = (health.success + 2.0) / (total + 3.0)
            latency_score = (
                1.0 / (1.0 + (health.latency_ewma_ms / 10000.0))
                if health.latency_ewma_ms > 0 else 0.5
            )
            config_score = 1.0 / (1.0 + index)
            failure_penalty = min(0.4, 0.1 * health.consecutive_failures)
            score = (
                reliability_weight * smoothed_reliability
                + latency_weight * latency_score
                + config_weight * config_score
                - failure_penalty
            )
            if health.is_cooling():
                evidence_class = "cooling"
                group = 3
                reason = "active cooldown"
            elif health.consecutive_failures > 0 or (
                total >= self.MIN_ADAPTIVE_OBSERVATIONS
                and raw_success_rate is not None
                and raw_success_rate < 0.5
            ):
                evidence_class = "known_unhealthy"
                group = 2
                reason = "recent failure streak or low observed success rate"
            elif total < self.MIN_ADAPTIVE_OBSERVATIONS:
                evidence_class = "unproven"
                group = 1
                reason = "insufficient observations; preserve configured order"
            else:
                evidence_class = "proven"
                group = 0
                reason = f"{policy} score from reliability and latency"
            entries.append({
                "profile": profile,
                "configured_index": index,
                "group": group,
                "score": score,
                "total": total,
                "success_rate": raw_success_rate,
                "latency_ewma_ms": health.latency_ewma_ms,
                "cooling": health.is_cooling(),
                "consecutive_failures": health.consecutive_failures,
                "evidence_class": evidence_class,
                "reason": reason,
            })

        if adaptive:
            entries.sort(key=lambda item: (
                int(item["group"]),
                int(item["configured_index"]) if item["evidence_class"] == "unproven"
                else -float(item["score"]),
                int(item["configured_index"]),
            ))

        ranked_profiles = [item["profile"] for item in entries]
        report_entries = []
        for rank, item in enumerate(entries):
            report_entries.append({
                "profile": item["profile"].name,
                "provider": item["profile"].provider,
                "configured_index": item["configured_index"],
                "adaptive_rank": rank,
                "changed": rank != item["configured_index"],
                "evidence_class": item["evidence_class"],
                "observations": item["total"],
                "success_rate": (
                    round(float(item["success_rate"]), 3)
                    if item["success_rate"] is not None else None
                ),
                "latency_ewma_ms": round(float(item["latency_ewma_ms"]), 1),
                "cooling": item["cooling"],
                "consecutive_failures": item["consecutive_failures"],
                "score": round(float(item["score"]), 4),
                "reason": item["reason"],
            })
        return ranked_profiles, {
            "role": role,
            "adaptive": bool(adaptive),
            "policy": policy if adaptive else "operator_explicit_order",
            "minimum_observations": self.MIN_ADAPTIVE_OBSERVATIONS,
            "configured_chain": [profile.name for profile in profiles],
            "effective_chain": [profile.name for profile in ranked_profiles],
            "eligible_chain": [
                item["profile"].name for item in entries if not item["cooling"]
            ],
            "changed": [profile.name for profile in profiles] != [profile.name for profile in ranked_profiles],
            "profiles": report_entries,
        }

    def snapshot(self) -> Dict[str, Dict]:
        now = time.time()
        out: Dict[str, Dict] = {}
        for name, h in self._stats.items():
            total = h.success + h.fail
            out[name] = {
                "success": h.success,
                "fail": h.fail,
                "total": total,
                "success_rate": round(h.success / total, 3) if total else None,
                "last_latency_ms": round(h.last_latency_ms, 1),
                "latency_ewma_ms": round(h.latency_ewma_ms, 1),
                "last_used_at": h.last_used_at,
                "last_used_iso": (
                    datetime.fromtimestamp(h.last_used_at).isoformat(timespec="seconds")
                    if h.last_used_at else None
                ),
                "last_error": h.last_error,
                "last_trigger": h.last_trigger,
                "last_success_at": h.last_success_at,
                "cooldown_remaining_s": max(0.0, round(h.cooldown_until - now, 1)),
                "effective_cooldown_seconds": round(h.effective_cooldown_seconds, 1),
                "cooling": h.is_cooling(now),
                "failover_count": h.failover_count,
                "consecutive_failures": h.consecutive_failures,
            }
        return out


# ─────────────────────────────────────────────────────────────────
# Failover orchestration
# ─────────────────────────────────────────────────────────────────

class AllProfilesFailedError(Exception):
    """Raised when primary + every chain profile failed."""
    def __init__(self, attempts: List[Dict]):
        self.attempts = attempts
        trail = ", ".join(
            f"{a.get('profile','?')}={a.get('trigger','?')}" for a in attempts
        )
        super().__init__(f"All {len(attempts)} profile(s) failed. Trail: {trail}")


# Type alias — caller-supplied function that performs ONE LLM call.
# Receives the resolved (provider, model, api_base, api_key) so call_with_failover
# can swap them per attempt without the caller knowing about the chain.
PrimaryCallable = Callable[..., Awaitable[str]]


async def call_with_failover(
    *,
    primary_call: PrimaryCallable,
    chain: List[ApiProfile],
    primary_profile_name: str,
    primary_provider: str,
    primary_model: str,
    primary_api_base: Optional[str],
    primary_api_key: Optional[str],
    role: str,
    tracker: HealthTracker,
    cfg: FailoverConfig,
    attempts_out: Optional[List[Dict]] = None,
    inject_error: Optional[Exception] = None,
) -> str:
    """Try primary; on failover-eligible error, walk `chain` skipping cooling/keyless.

    Args:
        primary_call: async fn called per attempt with kw args
                      (provider, model, api_base, api_key) returning the LLM text.
        chain: profiles to try after primary (in order).
        primary_*: primary attempt parameters (already resolved from NodeConfig).
        role: node role name — included in attempt records for the UI / logs.
        tracker: HealthTracker mutated in place.
        cfg: FailoverConfig — controls enabled flag + trigger_on whitelist.
        attempts_out: optional list to append per-attempt records (for stress tests).
        inject_error: TEST-ONLY — raise this exception on the very first attempt
                      instead of calling primary_call. Used by stress_test.py to
                      verify the chain triggers without consuming real quota.

    Returns:
        The text returned by the first successful attempt.

    Raises:
        AllProfilesFailedError: every candidate failed with a failover-eligible
                                error and the chain is exhausted.
        Exception: re-raised verbatim if classification returns NONE (e.g. a
                   JSON parse bug or 400 bad request — not a quota condition).
    """
    attempts: List[Dict] = [] if attempts_out is None else attempts_out

    primary_candidate = {
        "profile": primary_profile_name,
        "provider": primary_provider,
        "model": primary_model,
        "api_base": primary_api_base,
        "api_key": primary_api_key,
        "is_primary": True,
    }

    chain_candidates: List[Dict] = []
    for p in chain:
        if p.name == primary_profile_name:
            continue
        if tracker.get(p.name).is_cooling():
            attempts.append({
                "role": role, "profile": p.name,
                "trigger": FailoverTrigger.COOLING,
                "error": f"in cooldown ({round(tracker.get(p.name).cooldown_until - time.time(), 1)}s left)",
                "is_primary": False,
            })
            continue
        api_key = os.environ.get(p.api_key_env) if p.api_key_env else None
        # v8.5 — only NO_KEY when api_key_env is declared but env var missing.
        # When api_key_env is "" (anonymous provider like Pollinations), allow
        # through with api_key=None — the adapter will skip auth header.
        if p.api_key_env and not api_key:
            attempts.append({
                "role": role, "profile": p.name,
                "trigger": FailoverTrigger.NO_KEY,
                "error": f"env var {p.api_key_env} not set",
                "is_primary": False,
            })
            continue
        chain_candidates.append({
            "profile": p.name,
            "provider": p.provider,
            "model": p.default_model or primary_model,
            "api_base": p.api_base,
            "api_key": api_key,
            "is_primary": False,
        })

    # Skip primary if it's cooling AND we have at least one chain candidate.
    # When no chain is usable, primary is our only shot — try it anyway.
    primary_is_cooling = tracker.get(primary_profile_name).is_cooling()
    if primary_is_cooling:
        attempts.append({
            "role": role, "profile": primary_profile_name,
            "trigger": FailoverTrigger.COOLING,
            "error": f"primary cooling ({round(tracker.get(primary_profile_name).cooldown_until - time.time(), 1)}s left), skipping",
            "is_primary": True,
        })
        candidates = chain_candidates
    else:
        candidates = [primary_candidate, *chain_candidates]

    first = True
    for c in candidates:
        # Sibling nodes may change profile/provider health after candidates were
        # compiled. Recheck immediately before and after the shared queue wait.
        health = tracker.get(c["profile"])
        if health.is_cooling():
            attempts.append({
                "role": role,
                "profile": c["profile"],
                "trigger": FailoverTrigger.COOLING,
                "error": f"cooldown became active ({round(health.cooldown_until - time.time(), 1)}s left)",
                "is_primary": c["is_primary"],
            })
            continue

        slot = await provider_rate_limiter.wait_for_slot(c["provider"])
        queue_wait_ms = round(float(slot.get("waited_seconds") or 0.0) * 1000.0, 1)
        if not slot.get("allowed"):
            attempts.append({
                "role": role,
                "profile": c["profile"],
                "trigger": FailoverTrigger.COOLING,
                "error": f"provider queue blocked ({slot.get('retry_after_seconds', 0)}s left)",
                "is_primary": c["is_primary"],
                "queue_wait_ms": queue_wait_ms,
            })
            continue

        health = tracker.get(c["profile"])
        if health.is_cooling():
            attempts.append({
                "role": role,
                "profile": c["profile"],
                "trigger": FailoverTrigger.COOLING,
                "error": f"cooldown activated during queue wait ({round(health.cooldown_until - time.time(), 1)}s left)",
                "is_primary": c["is_primary"],
                "queue_wait_ms": queue_wait_ms,
            })
            continue

        t0 = time.time()
        try:
            if first and inject_error is not None:
                first = False
                raise inject_error
            first = False
            from services.inference_governor import model_call_scope
            with model_call_scope(
                role=role,
                provider=c["provider"],
                model=c["model"],
                profile=c["profile"],
            ):
                result = await primary_call(
                    provider=c["provider"],
                    model=c["model"],
                    api_base=c["api_base"],
                    api_key=c["api_key"],
                )
            latency_ms = (time.time() - t0) * 1000.0
            tracker.record_success(c["profile"], latency_ms)
            attempts.append({
                "role": role,
                "profile": c["profile"],
                "trigger": FailoverTrigger.OK,
                "latency_ms": round(latency_ms, 1),
                "is_primary": c["is_primary"],
                "queue_wait_ms": queue_wait_ms,
            })
            return result
        except Exception as e:  # noqa: BLE001 — we classify below
            trigger = classify_error(e)
            err_str = f"{type(e).__name__}: {str(e)[:240]}"
            # Request-level budget exhaustion is a controller decision, not a
            # provider failure. Do not poison provider health or cooldown state.
            if type(e).__name__ == "InferenceBudgetExceeded":
                attempts.append({
                    "role": role,
                    "profile": c["profile"],
                    "trigger": FailoverTrigger.NONE,
                    "error": err_str,
                    "is_primary": c["is_primary"],
                })
                raise
            should_failover = (
                cfg.enabled
                and trigger != FailoverTrigger.NONE
                and trigger in cfg.trigger_on
            )
            if trigger in (FailoverTrigger.HTTP_429, FailoverTrigger.QUOTA):
                retry_after = None
                if isinstance(e, httpx.HTTPStatusError):
                    try:
                        raw_retry_after = e.response.headers.get("retry-after")
                        retry_after = float(raw_retry_after) if raw_retry_after else None
                    except (TypeError, ValueError):
                        retry_after = None
                provider_rate_limiter.record_rate_limit(c["provider"], retry_after)
            # When should_failover, cool down the profile so subsequent requests
            # in the same window skip it (primary OR chain — both can be on cooldown).
            tracker.record_failure(
                c["profile"], trigger, err_str,
                cool_down=should_failover,
            )
            attempts.append({
                "role": role,
                "profile": c["profile"],
                "trigger": trigger,
                "error": err_str,
                "is_primary": c["is_primary"],
                "queue_wait_ms": queue_wait_ms,
            })
            if not should_failover:
                raise
            # else: continue to next candidate

    raise AllProfilesFailedError(attempts)
