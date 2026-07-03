"""
URUK Trinity Console — OpenTelemetry setup (v8.21 OTel-1).

Graceful instrumentation layer:
  * When OTEL_EXPORTER_OTLP_ENDPOINT is unset → tracer is a no-op (zero
    runtime cost beyond the empty context-manager).
  * When OTel packages are missing → falls back to a stub tracer so imports
    in trinity_console / app / etc. never fail. The console keeps working.
  * Sensitive-content scrubber enforces KAIROS_CORE prohibitions
    (2019-06-12 operator anchor, dates, emails, phone, IPs) **before** any
    span attribute is set on user-input or LLM-output strings.

Public API:
    setup_telemetry()      — idempotent; reads env, configures global provider
    tracer                 — module-level Tracer instance (always defined)
    scrub_sensitive(text)  — redact before logging to OTel
    set_llm_attrs(span, role, provider, model, ...)
                           — apply OTel gen_ai.* + uruk.* semantic-conventions

Env vars consulted at setup_telemetry() time:
    OTEL_EXPORTER_OTLP_ENDPOINT  — base OTLP-HTTP URL (e.g. http://localhost:4318).
                                   When unset, no exporter is attached
                                   (tracer is no-op).
    OTEL_DEBUG_CONSOLE           — "true" to also print spans to stdout
                                   (useful for local development).
    OTEL_SCRUB_SENSITIVE         — "false" to disable scrubbing.
                                   Default: scrubbing ENABLED (recommended).
    OTEL_SAMPLE_RATE             — "0.0".."1.0", default "1.0".
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, List, Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Graceful import fallback
# ─────────────────────────────────────────────────────────────────

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        ParentBasedTraceIdRatio,
    )
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        _OTLP_AVAILABLE = True
    except ImportError:
        OTLPSpanExporter = None
        _OTLP_AVAILABLE = False
    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover — defensive fallback for missing OTel
    _OTEL_AVAILABLE = False
    _OTLP_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────
# Stub tracer (used when OTel SDK isn't installed)
# ─────────────────────────────────────────────────────────────────

class _NoOpSpan:
    def __init__(self, name: str = "noop"):
        self.name = name
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def set_attribute(self, key: str, value: Any) -> None:
        return None
    def set_attributes(self, attrs: dict) -> None:
        return None
    def add_event(self, name: str, attributes: Optional[dict] = None) -> None:
        return None
    def set_status(self, status: Any) -> None:
        return None
    def record_exception(self, exc: BaseException) -> None:
        return None
    def is_recording(self) -> bool:
        return False
    def end(self) -> None:
        return None


class _NoOpTracer:
    """Drop-in tracer when OTel SDK isn't installed. All operations are no-ops."""
    def start_as_current_span(self, name: str, *args, **kwargs):
        return _NoOpSpan(name)
    def start_span(self, name: str, *args, **kwargs):
        return _NoOpSpan(name)


# Always defined — either real OTel tracer or no-op stub.
# Re-assigned by setup_telemetry() when SDK is configured.
if _OTEL_AVAILABLE:
    tracer = _otel_trace.get_tracer("uruk-trinity-console", "8.21")
else:
    tracer = _NoOpTracer()


# ─────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────

_TELEMETRY_INITIALIZED = False


def setup_telemetry(force: bool = False) -> dict:
    """Read env + configure global TracerProvider. Idempotent.

    Returns:
        dict — {"enabled": bool, "otlp_endpoint": str|None,
                "debug_console": bool, "sample_rate": float,
                "scrub_sensitive": bool, "reason": str}
    """
    global tracer, _TELEMETRY_INITIALIZED

    status: dict = {
        "enabled": False,
        "otlp_endpoint": None,
        "debug_console": False,
        "sample_rate": 1.0,
        "scrub_sensitive": True,
        "reason": "",
    }

    if _TELEMETRY_INITIALIZED and not force:
        status["reason"] = "already_initialized"
        status["enabled"] = isinstance(tracer, type(_otel_trace.get_tracer("x")) if _OTEL_AVAILABLE else _NoOpTracer)
        return status

    if not _OTEL_AVAILABLE:
        status["reason"] = "opentelemetry SDK not installed"
        _TELEMETRY_INITIALIZED = True
        return status

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
    debug_console = os.getenv("OTEL_DEBUG_CONSOLE", "false").strip().lower() == "true"
    scrub = os.getenv("OTEL_SCRUB_SENSITIVE", "true").strip().lower() != "false"
    try:
        sample_rate = float(os.getenv("OTEL_SAMPLE_RATE", "1.0"))
    except ValueError:
        sample_rate = 1.0
    sample_rate = max(0.0, min(1.0, sample_rate))

    status["otlp_endpoint"] = otlp_endpoint or None
    status["debug_console"] = debug_console
    status["sample_rate"] = sample_rate
    status["scrub_sensitive"] = scrub

    if not otlp_endpoint and not debug_console:
        status["reason"] = (
            "no OTEL_EXPORTER_OTLP_ENDPOINT set and OTEL_DEBUG_CONSOLE != true — "
            "instrumentation is no-op (zero runtime cost)"
        )
        _TELEMETRY_INITIALIZED = True
        return status

    # Build provider with sampler
    if sample_rate >= 1.0:
        sampler = ALWAYS_ON
    elif sample_rate <= 0.0:
        sampler = ALWAYS_OFF
    else:
        sampler = ParentBasedTraceIdRatio(sample_rate)

    resource = Resource.create({
        "service.name": "uruk-trinity-console",
        "service.version": "8.21",
        "deployment.environment": os.getenv("OTEL_DEPLOYMENT_ENV", "local"),
    })
    provider = TracerProvider(resource=resource, sampler=sampler)

    # OTLP HTTP exporter — universal target for Langfuse / Phoenix / Jaeger
    if otlp_endpoint and _OTLP_AVAILABLE:
        try:
            exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
            status["enabled"] = True
            log.info("OTel: OTLP exporter → %s/v1/traces", otlp_endpoint)
        except Exception as e:
            log.warning("OTel: OTLP exporter init failed: %s: %s",
                        type(e).__name__, e)

    # Optional console exporter for debug
    if debug_console:
        # Console debug output should be synchronous. A BatchSpanProcessor can
        # flush after pytest/stdout capture has closed, producing noisy
        # "I/O operation on closed file" exceptions even when tests pass.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        status["enabled"] = True
        log.info("OTel: console exporter ENABLED (debug)")

    _otel_trace.set_tracer_provider(provider)
    tracer = _otel_trace.get_tracer("uruk-trinity-console", "8.21")
    status["reason"] = "configured"
    _TELEMETRY_INITIALIZED = True
    return status


# ─────────────────────────────────────────────────────────────────
# Sensitive-content scrubber
# ─────────────────────────────────────────────────────────────────

# Patterns enforced from KAIROS_CORE.md "ABSOLUTE PROHIBITION" + standard PII.
# These are applied to any user-input / LLM-output text BEFORE span.set_attribute.
SENSITIVE_PATTERNS: List[tuple] = [
    # Operator's physical anchor — NEVER log per KAIROS_CORE
    (re.compile(r"\b2019-06-12\b"), "[REDACTED_ANCHOR]"),
    # Any ISO date — may carry operator-specific time-coord info
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "[REDACTED_DATE]"),
    # Email
    (re.compile(r"\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    # Phone (E.164 + common formats)
    (re.compile(r"\+\d{1,3}[\s-]?\(?\d{1,4}\)?[\s-]?\d{1,4}[\s-]?\d{1,9}"),
     "[REDACTED_PHONE]"),
    # IPv4
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
    # API keys (common formats: sk-..., ghp_..., pcsk-..., AKIA...)
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
]


def scrub_sensitive(text: Any, max_chars: int = 500) -> str:
    """Redact known-sensitive patterns; truncate to `max_chars`.

    Always returns a string (coerces None / non-string to empty / repr).
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    enabled = os.getenv("OTEL_SCRUB_SENSITIVE", "true").strip().lower() != "false"
    if enabled:
        for pattern, replacement in SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + f"...[+{len(text) - max_chars} chars]"
    return text


# ─────────────────────────────────────────────────────────────────
# Semantic-convention helpers (OTel gen_ai.* + URUK uruk.*)
# ─────────────────────────────────────────────────────────────────

def set_llm_request_attrs(span: Any, *, role: str, provider: str = "",
                          model: str = "", max_tokens: Optional[int] = None,
                          temperature: Optional[float] = None,
                          prompt: Optional[str] = None) -> None:
    """Apply OTel LLM-request semantic conventions + URUK trinity role tag."""
    if not getattr(span, "is_recording", lambda: True)():
        return
    span.set_attribute("uruk.role", role)
    if provider:
        span.set_attribute("gen_ai.system", provider)
    if model:
        span.set_attribute("gen_ai.request.model", model)
    if max_tokens is not None:
        span.set_attribute("gen_ai.request.max_tokens", int(max_tokens))
    if temperature is not None:
        span.set_attribute("gen_ai.request.temperature", float(temperature))
    if prompt is not None:
        span.set_attribute("gen_ai.prompt", scrub_sensitive(prompt))


def set_llm_response_attrs(span: Any, *, completion: Optional[str] = None,
                           input_tokens: Optional[int] = None,
                           output_tokens: Optional[int] = None,
                           finish_reason: Optional[str] = None,
                           latency_ms: Optional[float] = None) -> None:
    """Apply OTel LLM-response semantic conventions."""
    if not getattr(span, "is_recording", lambda: True)():
        return
    if completion is not None:
        span.set_attribute("gen_ai.completion", scrub_sensitive(completion))
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", int(input_tokens))
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", int(output_tokens))
    if finish_reason:
        span.set_attribute("gen_ai.response.finish_reasons", [finish_reason])
    if latency_ms is not None:
        span.set_attribute("uruk.llm.latency_ms", float(latency_ms))


def set_trinity_attrs(span: Any, *, verdict: Optional[str] = None,
                      veto_type: Optional[str] = None,
                      spirit_trigger_mode: Optional[str] = None,
                      threat_level: Optional[str] = None,
                      pain_intensity: Optional[float] = None,
                      council_verdict: Optional[str] = None) -> None:
    """Trinity-specific custom attributes."""
    if not getattr(span, "is_recording", lambda: True)():
        return
    if verdict is not None:
        span.set_attribute("uruk.verdict", verdict)
    if veto_type is not None:
        span.set_attribute("uruk.son_veto_type", veto_type)
    if spirit_trigger_mode is not None:
        span.set_attribute("uruk.spirit_trigger_mode", spirit_trigger_mode)
    if threat_level is not None:
        span.set_attribute("uruk.threat_level", threat_level)
    if pain_intensity is not None:
        span.set_attribute("uruk.pain_intensity", float(pain_intensity))
    if council_verdict is not None:
        span.set_attribute("uruk.council_verdict", council_verdict)


def emit_event(span: Any, name: str, **attrs) -> None:
    """Add a span event with attributes. Scrubs string values."""
    if not getattr(span, "add_event", None):
        return
    clean = {}
    for k, v in attrs.items():
        if isinstance(v, str):
            clean[k] = scrub_sensitive(v, max_chars=200)
        else:
            clean[k] = v
    span.add_event(name, attributes=clean)


# ─────────────────────────────────────────────────────────────────
# Idempotent auto-setup at import time
# ─────────────────────────────────────────────────────────────────

# Auto-setup runs once on import. The console can also call setup_telemetry()
# explicitly to re-read env (e.g. after nodes.yaml reload).
try:
    setup_telemetry()
except Exception as _e:  # pragma: no cover — never block module import
    log.warning("OTel auto-setup failed: %s: %s", type(_e).__name__, _e)
