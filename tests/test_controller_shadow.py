import tempfile
import unittest
from pathlib import Path

from services.controller_policy import compile_controller_decision
from services.controller_shadow import (
    compare_decisions,
    guard_controller_candidate,
    load_shadow_config,
    run_shadow_once,
)


ROOT = Path(__file__).resolve().parent.parent


class ControllerShadowTests(unittest.TestCase):
    def test_compare_decisions_tracks_route_and_authority(self):
        reference = compile_controller_decision("Open browser and inspect the page.", root=ROOT)
        candidate = dict(reference)
        candidate["route_kind"] = "small_task"
        candidate["task_profile"] = "local_language"
        candidate["tool_permission"] = "none"
        candidate["escalation_required"] = False
        candidate["reason_codes"] = ["route.small_task", "policy.local_worker_allowed"]

        comparison = compare_decisions(reference, candidate)

        self.assertFalse(comparison["route_match"])
        self.assertFalse(comparison["authority_match"])
        self.assertFalse(comparison["escalation_match"])
        self.assertIn("route_kind", comparison["differences"])

    def test_disabled_shadow_does_not_call_server_or_write_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_shadow_config(root)
            result = run_shadow_once("What is freedom?", root=root)

        self.assertFalse(config["enabled"])
        self.assertEqual(result, {"status": "disabled"})

    def test_authority_guard_accepts_route_but_overrides_permission(self):
        reference = compile_controller_decision(
            "Process this request using forced mode tool_workshop.",
            root=ROOT,
            pipeline_mode="tool_workshop",
        )
        candidate = dict(reference)
        candidate["tool_permission"] = "read_only"

        guarded, guard = guard_controller_candidate(reference, candidate)

        self.assertTrue(guard["route_accepted"])
        self.assertFalse(guard["fallback_used"])
        self.assertIn("tool_permission", guard["overridden_fields"])
        self.assertEqual(guarded, reference)

    def test_authority_guard_falls_back_when_route_is_wrong(self):
        reference = compile_controller_decision("Open browser and inspect the page.", root=ROOT)
        candidate = dict(reference)
        candidate["route_kind"] = "small_task"
        candidate["task_profile"] = "local_language"
        candidate["tool_permission"] = "none"
        candidate["escalation_required"] = False
        candidate["reason_codes"] = ["route.small_task", "policy.local_worker_allowed"]

        guarded, guard = guard_controller_candidate(reference, candidate)

        self.assertFalse(guard["route_accepted"])
        self.assertTrue(guard["fallback_used"])
        self.assertEqual(guard["fallback_reason"], "route_mismatch")
        self.assertEqual(guarded, reference)


if __name__ == "__main__":
    unittest.main(verbosity=2)
