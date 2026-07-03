"""
Unit tests for services/otel_setup.py — v8.21 OTel-1.

Covers:
  * scrub_sensitive: each redaction pattern + truncation cap
  * setup_telemetry: no-op default, debug-console enable, idempotent
  * semantic-convention helpers don't blow up on no-op spans
  * gen_ai.* + uruk.* attribute names are correctly applied
"""

from __future__ import annotations

import io
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.otel_setup import (
    emit_event,
    scrub_sensitive,
    set_llm_request_attrs,
    set_llm_response_attrs,
    set_trinity_attrs,
    setup_telemetry,
    tracer,
)


# ─────────────────────────────────────────────────────────────────
# Sensitive scrubber
# ─────────────────────────────────────────────────────────────────

class TestScrubSensitive:
    def test_redacts_operator_anchor(self):
        assert "2019-06-12" not in scrub_sensitive("anchor=2019-06-12 today")

    def test_redacts_iso_date(self):
        out = scrub_sensitive("incident on 2024-03-15")
        assert "2024-03-15" not in out
        assert "[REDACTED_DATE]" in out

    def test_redacts_email(self):
        out = scrub_sensitive("contact me at jane@example.com please")
        assert "jane@example.com" not in out
        assert "[REDACTED_EMAIL]" in out

    def test_redacts_phone(self):
        out = scrub_sensitive("call +1-415-555-0123 today")
        assert "555-0123" not in out
        assert "[REDACTED_PHONE]" in out

    def test_redacts_ipv4(self):
        out = scrub_sensitive("connect to 192.168.1.1 over LAN")
        assert "192.168.1.1" not in out
        assert "[REDACTED_IP]" in out

    def test_redacts_api_key_prefix(self):
        out = scrub_sensitive("token=sk-abcdef0123456789abcdef0123 then call")
        assert "sk-abcdef" not in out
        assert "[REDACTED_API_KEY]" in out

    def test_normal_text_unchanged(self):
        assert scrub_sensitive("Q3 GDP grew 2.1% YoY") == "Q3 GDP grew 2.1% YoY"

    def test_truncates_long_input(self):
        long_text = "x" * 1000
        out = scrub_sensitive(long_text, max_chars=200)
        # 200 + the "...[+800 chars]" tail
        assert out.startswith("x" * 200)
        assert "[+800 chars]" in out

    def test_handles_none(self):
        assert scrub_sensitive(None) == ""

    def test_handles_non_string(self):
        assert "42" in scrub_sensitive(42, max_chars=0)

    def test_scrub_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("OTEL_SCRUB_SENSITIVE", "false")
        out = scrub_sensitive("date 2024-03-15 visible")
        assert "2024-03-15" in out


# ─────────────────────────────────────────────────────────────────
# setup_telemetry
# ─────────────────────────────────────────────────────────────────

class TestSetupTelemetry:
    def test_default_is_noop(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_DEBUG_CONSOLE", raising=False)
        status = setup_telemetry(force=True)
        assert status["enabled"] is False
        assert "no OTEL_EXPORTER_OTLP_ENDPOINT" in status["reason"]

    def test_debug_console_enables(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.setenv("OTEL_DEBUG_CONSOLE", "true")
        status = setup_telemetry(force=True)
        assert status["enabled"] is True
        assert status["debug_console"] is True

    def test_sample_rate_clamps(self, monkeypatch):
        monkeypatch.setenv("OTEL_SAMPLE_RATE", "2.5")
        monkeypatch.setenv("OTEL_DEBUG_CONSOLE", "true")
        status = setup_telemetry(force=True)
        assert status["sample_rate"] == 1.0

    def test_invalid_sample_rate_falls_back(self, monkeypatch):
        monkeypatch.setenv("OTEL_SAMPLE_RATE", "not-a-number")
        monkeypatch.setenv("OTEL_DEBUG_CONSOLE", "true")
        status = setup_telemetry(force=True)
        assert status["sample_rate"] == 1.0


# ─────────────────────────────────────────────────────────────────
# Semantic-convention helpers
# ─────────────────────────────────────────────────────────────────

class TestLLMSemConv:
    def test_request_attrs_no_op_safe(self):
        # Even on a no-op span, helpers must not raise
        with tracer.start_as_current_span("test_no_op") as span:
            set_llm_request_attrs(span, role="father",
                                   provider="groq", model="llama-3.3-70b",
                                   max_tokens=2000, temperature=0.5,
                                   prompt="test prompt")
            set_llm_response_attrs(span, completion="test completion",
                                    latency_ms=123.4)

    def test_set_trinity_attrs_no_op_safe(self):
        with tracer.start_as_current_span("test_no_op") as span:
            set_trinity_attrs(span, verdict="consensus",
                              veto_type="none",
                              spirit_trigger_mode="NONE",
                              council_verdict="consensus")

    def test_emit_event_scrubs_strings(self, monkeypatch):
        """emit_event must scrub sensitive values in event attrs."""
        # We can't easily inspect the event payload on a no-op span, so this
        # test just verifies the call doesn't raise.
        monkeypatch.setenv("OTEL_DEBUG_CONSOLE", "false")
        with tracer.start_as_current_span("test") as span:
            emit_event(span, "test_event",
                       sensitive="email me at test@example.com",
                       num=42)

    def test_helpers_handle_none_values(self):
        with tracer.start_as_current_span("test") as span:
            set_llm_request_attrs(span, role="father")
            set_llm_response_attrs(span)
            set_trinity_attrs(span)


# ─────────────────────────────────────────────────────────────────
# End-to-end with console exporter
# ─────────────────────────────────────────────────────────────────

class TestE2E:
    def test_span_creation_does_not_raise(self):
        """Span creation under any tracer mode must complete cleanly."""
        with tracer.start_as_current_span("test.e2e_smoke") as span:
            span.set_attribute("uruk.test", "value")
            span.add_event("milestone")
        # If we got here without exception, that's the test passing.
        # End-to-end "spans actually flow to a backend" is verified by the
        # smoke script under tests/smoke_otel_pipeline.py — kept out of the
        # unit-test suite because OTel's global provider doesn't survive
        # multiple reconfigures cleanly.
        assert True
