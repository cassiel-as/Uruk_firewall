"""Bounded small-model executor for low-level runtime tasks.

This module is intentionally narrow.  It lets the runtime delegate cheap,
low-risk work to task-specific local model profiles while keeping deterministic
fallbacks and explicit guardrails around anything that should remain in the
full Trinity pipeline.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional

from services.task_profiles import get_task_profile, profile_api_key
from services.local_model_router import effective_timeout, select_local_model
from services.runtime_identity import with_runtime_identity
from services.protocol_concepts import is_protocol_concept_query


LOW_RISK_TASKS = frozenset({
    "classify",
    "extract_json",
    "normalize_json",
    "summarize",
    "compress_context",
    "extract_entities",
    "rewrite_query",
    "answer_simple",
})

MAX_LOW_LEVEL_CHARS = 6000
MODEL_TASK_MIN_TIMEOUT_SECONDS = 5.0

_FORCE_HEAVY_PATTERNS = (
    "/firewall",
    "/blackbox",
    "/scr",
    "/news",
    "/sovereign",
    "trinity",
    "kairos",
    "coordinate theory",
    "self-upgrade",
    "self upgrade",
    "upgrade system",
    "install tool",
    "delete file",
    "write file",
    "run command",
    "execute command",
    "api key",
    "password",
    "secret",
    "自由",
    "自由度",
    "freedom",
    "liberty",
    "freedom_loss",
    "freedom_loss_entropy",
    "座標說",
    "抽象概念",
    "民主",
    "文明",
    "主權",
    "自治",
    "尊嚴",
    "存在",
    "意義",
    "真理",
    "價值",
    "靈魂",
)

_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")

ChatFn = Callable[..., Awaitable[str] | str]


def _result(
    *,
    ok: bool,
    task: str,
    source: str,
    text: str = "",
    data: Optional[dict[str, Any]] = None,
    profile_name: str = "small",
    profile: Optional[Mapping[str, Any]] = None,
    latency_ms: float = 0.0,
    warnings: Optional[list[str]] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    profile = profile or {}
    return {
        "ok": bool(ok),
        "task": task,
        "source": source,
        "text": text,
        "data": data or {},
        "profile": profile_name,
        "provider": str(profile.get("provider") or ""),
        "model": str(profile.get("model") or ""),
        "latency_ms": round(float(latency_ms), 1),
        "warnings": warnings or [],
        "error": error,
        "routing": dict(profile.get("_routing") or {}),
    }


def _coerce_text(text: Any) -> str:
    return "" if text is None else str(text)


def _language_instruction(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "Output language: Traditional Chinese. Preserve Cantonese wording when present."
    return "Output language: same as the input."


def _guard_low_risk(task: str, text: str) -> Optional[str]:
    if task not in LOW_RISK_TASKS:
        return f"unsupported task: {task}"
    if len(text) > MAX_LOW_LEVEL_CHARS:
        return f"input too long for small-task executor: {len(text)} chars"
    lower = text.lower()
    if task == "answer_simple" and (
        is_protocol_concept_query(text) or any(p in lower for p in _FORCE_HEAVY_PATTERNS)
    ):
        return "query requires full pipeline or deterministic tool path"
    return None


def _extract_json_text(text: str) -> Optional[str]:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        json.loads(stripped)
        return stripped
    except Exception:
        pass

    starts = [i for i, ch in enumerate(text) if ch in "[{"]
    pairs = {"{": "}", "[": "]"}
    for start in starts:
        opening = text[start]
        closing = pairs[opening]
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except Exception:
                        break
    return None


def extract_json(text: str) -> dict[str, Any]:
    json_text = _extract_json_text(text)
    if json_text is None:
        return {"ok": False, "error": "no JSON object or array found"}
    try:
        parsed = json.loads(json_text)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "json_text": json_text, "value": parsed}


def deterministic_summary(text: str, max_sentences: int = 3, max_chars: int = 700) -> str:
    text = re.sub(r"\s+", " ", _coerce_text(text)).strip()
    if not text:
        return ""
    pieces = [p.strip() for p in _SENTENCE_RE.split(text) if p.strip()]
    if len(pieces) <= 1:
        return text[:max_chars]
    summary = " ".join(pieces[:max(1, max_sentences)])
    return summary[:max_chars].rstrip()


async def _maybe_await(value: Awaitable[str] | str) -> str:
    if inspect.isawaitable(value):
        return await value
    return str(value)


async def _call_small_model(
    *,
    profile: Mapping[str, Any],
    system: str,
    message: str,
    chat_fn: Optional[ChatFn],
    timeout: float,
    max_tokens: int,
    role: str,
) -> str:
    if chat_fn is None:
        from services.local_llm_discovery import quick_chat

        chat_fn = quick_chat

    call = chat_fn(
        api_base=profile.get("api_base") or "http://localhost:11434",
        provider=profile.get("provider") or "ollama",
        model=profile.get("model") or "qwen2.5:3b",
        message=message,
        system=system,
        timeout=timeout,
        api_key=profile_api_key(profile),
        max_tokens=max_tokens,
        temperature=float(profile.get("temperature") or 0.0),
        think=bool(profile.get("think", False)),
        keep_alive=str(profile.get("keep_alive") or "15m"),
        context_window=int(profile.get("context_window") or 8192),
        role=role,
    )
    return await _maybe_await(call)


async def run_small_task(
    task: str,
    text: Any,
    *,
    config_dir: str | Path = "config",
    profile_name: str = "auto",
    options: Optional[Mapping[str, Any]] = None,
    chat_fn: Optional[ChatFn] = None,
) -> dict[str, Any]:
    """Run one low-level task through deterministic logic or a small model.

    The function never raises for model/network failures.  Callers can inspect
    ``ok`` and either use the result or fall back to the full pipeline.
    """
    task = (task or "classify").strip().lower()
    text = _coerce_text(text)
    options = dict(options or {})
    decision = select_local_model(
        task,
        text,
        config_dir=config_dir,
        requested_profile=profile_name,
    )
    resolved_profile_name = decision.profile_name or profile_name
    profile = (
        dict(get_task_profile(resolved_profile_name, config_dir))
        if decision.execution == "local_model"
        else {}
    )
    profile["_routing"] = decision.to_dict()
    profile_name = resolved_profile_name
    blocked = _guard_low_risk(task, text)
    if decision.escalation_required:
        blocked = decision.reason
    if blocked:
        return _result(
            ok=False,
            task=task,
            source="blocked",
            profile_name=profile_name,
            profile=profile,
            error=blocked,
        )

    t0 = time.time()

    if task == "extract_json":
        parsed = extract_json(text)
        return _result(
            ok=bool(parsed.get("ok")),
            task=task,
            source="deterministic",
            text=parsed.get("json_text", ""),
            data=parsed,
            profile_name=profile_name,
            profile=profile,
            latency_ms=(time.time() - t0) * 1000,
            error=parsed.get("error"),
        )

    if task == "normalize_json":
        parsed = extract_json(text)
        if not parsed.get("ok"):
            return _result(
                ok=False,
                task=task,
                source="deterministic",
                data=parsed,
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
                error=parsed.get("error"),
            )
        normalized = json.dumps(
            parsed["value"],
            ensure_ascii=False,
            sort_keys=bool(options.get("sort_keys", True)),
            indent=int(options.get("indent", 2)),
        )
        return _result(
            ok=True,
            task=task,
            source="deterministic",
            text=normalized,
            data={"value": parsed["value"]},
            profile_name=profile_name,
            profile=profile,
            latency_ms=(time.time() - t0) * 1000,
        )

    if task == "classify":
        from services.pre_gate import classify

        timeout = (
            await effective_timeout(profile)
            if chat_fn is None
            else float(profile.get("timeout_seconds") or 12.0)
        )
        data = await classify(
            text,
            provider=str(profile.get("provider") or "ollama"),
            model=str(profile.get("model") or "qwen2.5:3b"),
            api_base=str(profile.get("api_base") or "http://localhost:11434"),
            api_key=profile_api_key(profile),
            timeout=timeout,
            temperature=float(profile.get("temperature") or 0.0),
            think=bool(profile.get("think", False)),
            keep_alive=str(profile.get("keep_alive") or "30m"),
        )
        return _result(
            ok=True,
            task=task,
            source=str(data.get("source") or "classifier"),
            text=str(data.get("type") or ""),
            data=data,
            profile_name=profile_name,
            profile=profile,
            latency_ms=(time.time() - t0) * 1000,
        )

    timeout = float(
        options.get("timeout_seconds")
        or (
            await effective_timeout(profile)
            if chat_fn is None
            else profile.get("timeout_seconds")
        )
        or 15.0
    )
    timeout = max(timeout, MODEL_TASK_MIN_TIMEOUT_SECONDS)
    max_tokens = int(options.get("max_tokens") or profile.get("max_tokens") or 512)

    if task in {"summarize", "compress_context"}:
        system = (
            "You are a bounded background text compressor. Preserve the input "
            "language, facts, dates, names, uncertainty, and causal relations. "
            "Return only a concise summary. Do not add claims or make decisions."
        )
        message = (
            f"{_language_instruction(text)}\n"
            f"Write a summary in {int(options.get('sentences', 3))} sentences or fewer.\n\n"
            f"TEXT:\n{text}"
        )
        try:
            raw = await asyncio.wait_for(
                _call_small_model(
                    profile=profile,
                    system=system,
                    message=message,
                    chat_fn=chat_fn,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    role=f"local_task:{task}",
                ),
                timeout=timeout + 0.5,
            )
            cleaned = raw.strip()
            refusal_markers = (
                "please provide a text",
                "cannot summarize",
                "can't summarize",
                "exceeds the instruction limit",
                "a concise summary would",
                "for a summary that should",
                "sentences are irrelevant",
            )
            if any(marker in cleaned.lower() for marker in refusal_markers):
                raise ValueError("small model refused summarization task")
            return _result(
                ok=True,
                task=task,
                source="small_model",
                text=cleaned,
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
            )
        except Exception as exc:
            return _result(
                ok=True,
                task=task,
                source="deterministic_fallback",
                text=deterministic_summary(
                    text,
                    max_sentences=int(options.get("sentences", 3)),
                    max_chars=int(options.get("max_chars", 700)),
                ),
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
                warnings=[f"small_model_unavailable:{type(exc).__name__}"],
            )

    if task == "answer_simple":
        system = with_runtime_identity(
            "You are a small low-level assistant. Answer simple factual or "
            "formatting questions directly in the user's language. If the task needs deep reasoning, "
            "fresh web data, private data, or system changes, reply exactly: "
            "__NEEDS_FULL_PIPELINE__."
        )
        try:
            raw = await asyncio.wait_for(
                _call_small_model(
                    profile=profile,
                    system=system,
                    message=f"{_language_instruction(text)}\n\n{text}",
                    chat_fn=chat_fn,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    role=f"local_task:{task}",
                ),
                timeout=timeout + 0.5,
            )
            raw = raw.strip()
            if raw == "__NEEDS_FULL_PIPELINE__":
                return _result(
                    ok=False,
                    task=task,
                    source="small_model",
                    profile_name=profile_name,
                    profile=profile,
                    latency_ms=(time.time() - t0) * 1000,
                    error="small model requested full pipeline",
                )
            return _result(
                ok=bool(raw),
                task=task,
                source="small_model",
                text=raw,
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
                error=None if raw else "empty small-model response",
            )
        except Exception as exc:
            return _result(
                ok=False,
                task=task,
                source="fallback_required",
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

    if task == "extract_entities":
        system = (
            "Extract entities without interpretation. Return one JSON object with "
            "arrays named people, organizations, locations, dates, and topics. "
            "Use only values explicitly present in the input."
        )
        try:
            raw = await asyncio.wait_for(
                _call_small_model(
                    profile=profile,
                    system=system,
                    message=f"{_language_instruction(text)}\n\n{text}",
                    chat_fn=chat_fn,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    role=f"local_task:{task}",
                ),
                timeout=timeout + 0.5,
            )
            parsed = extract_json(raw)
            if not parsed.get("ok") or not isinstance(parsed.get("value"), dict):
                raise ValueError("local model did not return a JSON object")
            return _result(
                ok=True,
                task=task,
                source="small_model",
                text=parsed.get("json_text", ""),
                data=parsed.get("value", {}),
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
            )
        except Exception as exc:
            return _result(
                ok=False,
                task=task,
                source="fallback_required",
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

    if task == "rewrite_query":
        system = (
            "Rewrite the input as one compact retrieval query. Preserve names, "
            "dates, and the user's language. Return the query only. Do not answer it."
        )
        try:
            raw = await asyncio.wait_for(
                _call_small_model(
                    profile=profile,
                    system=system,
                    message=f"{_language_instruction(text)}\n\n{text}",
                    chat_fn=chat_fn,
                    timeout=timeout,
                    max_tokens=min(max_tokens, 128),
                    role=f"local_task:{task}",
                ),
                timeout=timeout + 0.5,
            )
            rewritten = raw.strip().splitlines()[0][:500]
            return _result(
                ok=bool(rewritten),
                task=task,
                source="small_model",
                text=rewritten,
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
                error=None if rewritten else "empty rewritten query",
            )
        except Exception as exc:
            return _result(
                ok=False,
                task=task,
                source="fallback_required",
                profile_name=profile_name,
                profile=profile,
                latency_ms=(time.time() - t0) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

    return _result(
        ok=False,
        task=task,
        source="blocked",
        profile_name=profile_name,
        profile=profile,
        error=f"unsupported task: {task}",
    )


def profile_summary(config_dir: str | Path = "config", profile_name: str = "auto") -> dict[str, Any]:
    decision = select_local_model("answer_simple", "", config_dir=config_dir, requested_profile=profile_name)
    resolved_profile = decision.profile_name or profile_name
    profile = get_task_profile(resolved_profile, config_dir)
    return {
        "profile": resolved_profile,
        "provider": profile.get("provider"),
        "model": profile.get("model"),
        "api_base": profile.get("api_base"),
        "max_tokens": profile.get("max_tokens"),
        "context_window": profile.get("context_window"),
        "timeout_seconds": profile.get("timeout_seconds"),
        "cold_start_timeout_seconds": profile.get("cold_start_timeout_seconds"),
        "model_task_min_timeout_seconds": MODEL_TASK_MIN_TIMEOUT_SECONDS,
        "low_risk_tasks": sorted(LOW_RISK_TASKS),
        "max_input_chars": MAX_LOW_LEVEL_CHARS,
        "routing_policy": "task_aware_local_workers",
    }
