import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx

from failover import (
    AllProfilesFailedError,
    ApiProfile,
    FailoverConfig,
    FailoverTrigger,
    HealthTracker,
    call_with_failover,
    classify_error,
)
from services.inference_governor import (
    InferenceBudgetExceeded,
)


def _status_error(code: int, text: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
    response = httpx.Response(code, text=text, request=request)
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)


class FailoverClassificationTests(unittest.TestCase):
    def test_payload_too_large_is_profile_misconfig(self):
        self.assertEqual(classify_error(_status_error(413, "Payload Too Large")), FailoverTrigger.MISCONFIG)

    def test_auth_error_without_quota_signal_does_not_failover(self):
        self.assertEqual(classify_error(_status_error(401, "invalid api key")), FailoverTrigger.NONE)


class HealthTrackerTests(unittest.TestCase):
    def test_repeated_provider_failures_extend_cooldown_and_success_resets_streak(self):
        tracker = HealthTracker(cooldown_seconds=10)

        tracker.record_failure("provider", FailoverTrigger.HTTP_429, "rate limit", cool_down=True)
        first = tracker.get("provider")
        self.assertEqual(first.consecutive_failures, 1)
        self.assertEqual(first.effective_cooldown_seconds, 10)

        tracker.record_failure("provider", FailoverTrigger.HTTP_429, "rate limit", cool_down=True)
        second = tracker.get("provider")
        self.assertEqual(second.consecutive_failures, 2)
        self.assertEqual(second.effective_cooldown_seconds, 20)

        tracker.record_success("provider", latency_ms=100)
        self.assertEqual(tracker.get("provider").consecutive_failures, 0)

    def test_manual_cooldown_clear_resets_failure_streak(self):
        tracker = HealthTracker(cooldown_seconds=10)
        tracker.record_failure("provider", FailoverTrigger.HTTP_429, "rate limit", cool_down=True)

        tracker.clear_cooldown("provider")

        health = tracker.get("provider")
        self.assertFalse(health.is_cooling())
        self.assertEqual(health.consecutive_failures, 0)
        self.assertEqual(health.effective_cooldown_seconds, 0)

    def test_health_state_survives_tracker_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "provider_health.json"
            first = HealthTracker(cooldown_seconds=30, state_path=state_path)
            first.record_failure("provider", FailoverTrigger.HTTP_429, "rate limit", cool_down=True)

            restored = HealthTracker(cooldown_seconds=30, state_path=state_path)

            health = restored.get("provider")
            self.assertEqual(health.fail, 1)
            self.assertEqual(health.consecutive_failures, 1)
            self.assertTrue(health.is_cooling())
            self.assertIsNone(restored.persistence_status()["load_error"])

    def test_expired_persisted_cooldown_does_not_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "provider_health.json"
            state_path.write_text(json.dumps({
                "schema_version": HealthTracker.STATE_SCHEMA_VERSION,
                "saved_at": time.time() - 100,
                "profiles": {
                    "provider": {
                        "fail": 2,
                        "cooldown_until": time.time() - 1,
                        "consecutive_failures": 2,
                        "effective_cooldown_seconds": 60,
                    },
                },
            }), encoding="utf-8")

            restored = HealthTracker(cooldown_seconds=30, state_path=state_path)

            health = restored.get("provider")
            self.assertFalse(health.is_cooling())
            self.assertEqual(health.consecutive_failures, 0)
            self.assertEqual(health.effective_cooldown_seconds, 0)

    def test_corrupt_persisted_state_does_not_block_tracker(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "provider_health.json"
            state_path.write_text("{broken", encoding="utf-8")

            tracker = HealthTracker(cooldown_seconds=30, state_path=state_path)
            tracker.record_success("provider", latency_ms=50)

            self.assertIsNotNone(tracker.persistence_status()["load_error"])
            self.assertIsNone(tracker.persistence_status()["persist_error"])
            self.assertEqual(tracker.get("provider").success, 1)

    def test_invalid_profile_is_skipped_without_losing_valid_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "provider_health.json"
            state_path.write_text(json.dumps({
                "schema_version": HealthTracker.STATE_SCHEMA_VERSION,
                "saved_at": time.time(),
                "profiles": {
                    "valid": {"success": 2, "last_latency_ms": 25},
                    "invalid": {"success": "not-a-number"},
                },
            }), encoding="utf-8")

            tracker = HealthTracker(cooldown_seconds=30, state_path=state_path)

            self.assertEqual(tracker.get("valid").success, 2)
            self.assertNotIn("invalid", tracker.snapshot())
            self.assertEqual(tracker.persistence_status()["skipped_profiles"], 1)

    def test_unproven_profiles_preserve_configured_order(self):
        tracker = HealthTracker(cooldown_seconds=30)
        profiles = [
            ApiProfile(name="first", provider="a"),
            ApiProfile(name="second", provider="b"),
        ]

        ranked, report = tracker.rank_profiles(profiles, role="dispatcher")

        self.assertEqual([item.name for item in ranked], ["first", "second"])
        self.assertFalse(report["changed"])

    def test_known_unhealthy_profile_is_demoted(self):
        tracker = HealthTracker(cooldown_seconds=0)
        profiles = [
            ApiProfile(name="bad", provider="a"),
            ApiProfile(name="unproven", provider="b"),
        ]
        tracker.record_failure("bad", FailoverTrigger.HTTP_429, "rate limit", cool_down=True)

        ranked, report = tracker.rank_profiles(profiles, role="dispatcher")

        self.assertEqual([item.name for item in ranked], ["unproven", "bad"])
        self.assertTrue(report["changed"])

    def test_task_policy_changes_reliable_slow_vs_fast_choice(self):
        tracker = HealthTracker(cooldown_seconds=30)
        profiles = [
            ApiProfile(name="slow_reliable", provider="a"),
            ApiProfile(name="fast_less_reliable", provider="b"),
        ]
        slow = tracker.get("slow_reliable")
        slow.success = 5
        slow.latency_ewma_ms = 30000
        fast = tracker.get("fast_less_reliable")
        fast.success = 4
        fast.fail = 1
        fast.latency_ewma_ms = 2000

        quality_ranked, quality_report = tracker.rank_profiles(profiles, role="council")
        latency_ranked, latency_report = tracker.rank_profiles(profiles, role="dispatcher")

        self.assertEqual(quality_ranked[0].name, "slow_reliable")
        self.assertEqual(latency_ranked[0].name, "fast_less_reliable")
        self.assertEqual(quality_report["policy"], "reliability_sensitive")
        self.assertEqual(latency_report["policy"], "latency_sensitive")

    def test_explicit_fallback_order_is_not_reordered(self):
        tracker = HealthTracker(cooldown_seconds=30)
        profiles = [
            ApiProfile(name="bad", provider="a"),
            ApiProfile(name="good", provider="b"),
        ]
        tracker.get("bad").fail = 5
        tracker.get("good").success = 5

        ranked, report = tracker.rank_profiles(profiles, role="council", adaptive=False)

        self.assertEqual([item.name for item in ranked], ["bad", "good"])
        self.assertEqual(report["policy"], "operator_explicit_order")


class FailoverFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_413_fails_over_and_cools_broken_profile(self):
        tracker = HealthTracker(cooldown_seconds=30)
        cfg = FailoverConfig(trigger_on=[FailoverTrigger.MISCONFIG])
        calls = []

        async def primary_call(*, provider, model, api_base, api_key):
            calls.append(provider)
            if provider == "primary":
                raise _status_error(413, "Payload Too Large")
            return "ok"

        result = await call_with_failover(
            primary_call=primary_call,
            chain=[ApiProfile(name="fallback", provider="fallback", default_model="fallback-model")],
            primary_profile_name="primary",
            primary_provider="primary",
            primary_model="primary-model",
            primary_api_base=None,
            primary_api_key=None,
            role="test",
            tracker=tracker,
            cfg=cfg,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(calls, ["primary", "fallback"])
        self.assertTrue(tracker.get("primary").is_cooling())

    async def test_cooling_profile_is_skipped(self):
        tracker = HealthTracker(cooldown_seconds=30)
        tracker.get("primary").cooldown_until = time.time() + 30
        cfg = FailoverConfig(trigger_on=[FailoverTrigger.HTTP_429])
        calls = []

        async def primary_call(*, provider, model, api_base, api_key):
            calls.append(provider)
            return "ok"

        result = await call_with_failover(
            primary_call=primary_call,
            chain=[ApiProfile(name="fallback", provider="fallback", default_model="fallback-model")],
            primary_profile_name="primary",
            primary_provider="primary",
            primary_model="primary-model",
            primary_api_base=None,
            primary_api_key=None,
            role="test",
            tracker=tracker,
            cfg=cfg,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(calls, ["fallback"])

    async def test_cooling_primary_without_fallback_fails_fast(self):
        tracker = HealthTracker(cooldown_seconds=30)
        tracker.get("primary").cooldown_until = time.time() + 30
        cfg = FailoverConfig(trigger_on=[FailoverTrigger.HTTP_429])
        calls = []

        async def primary_call(*, provider, model, api_base, api_key):
            calls.append(provider)
            return "should-not-run"

        with self.assertRaises(AllProfilesFailedError) as raised:
            await call_with_failover(
                primary_call=primary_call,
                chain=[],
                primary_profile_name="primary",
                primary_provider="primary-no-fallback",
                primary_model="primary-model",
                primary_api_base=None,
                primary_api_key=None,
                role="test",
                tracker=tracker,
                cfg=cfg,
            )

        self.assertEqual(calls, [])
        self.assertEqual(raised.exception.attempts[0]["trigger"], FailoverTrigger.COOLING)

    async def test_budget_exhaustion_does_not_poison_provider_health(self):
        tracker = HealthTracker(cooldown_seconds=30)
        cfg = FailoverConfig(trigger_on=[FailoverTrigger.HTTP_429])

        async def primary_call(*, provider, model, api_base, api_key):
            raise InferenceBudgetExceeded("request-level budget exhausted")

        with self.assertRaises(InferenceBudgetExceeded):
            await call_with_failover(
                primary_call=primary_call,
                chain=[],
                primary_profile_name="primary",
                primary_provider="primary",
                primary_model="primary-model",
                primary_api_base=None,
                primary_api_key=None,
                role="test",
                tracker=tracker,
                cfg=cfg,
            )

        health = tracker.get("primary")
        self.assertEqual(health.fail, 0)
        self.assertEqual(health.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
