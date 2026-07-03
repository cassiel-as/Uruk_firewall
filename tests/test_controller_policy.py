import unittest
from pathlib import Path

from services.controller_policy import compile_controller_decision, compile_controller_example_input
from training.dataset_validator import validate_controller_decision


ROOT = Path(__file__).resolve().parent.parent


class ControllerPolicyTests(unittest.TestCase):
    def test_small_task_uses_bounded_local_profile(self):
        decision = compile_controller_decision("What is the capital of France?", root=ROOT)

        self.assertEqual(decision["route_kind"], "small_task")
        self.assertEqual(decision["task_profile"], "local_language")
        self.assertFalse(decision["escalation_required"])
        self.assertEqual(validate_controller_decision(decision), [])

    def test_protocol_concept_requires_strong_reasoning(self):
        decision = compile_controller_decision("What is freedom?", root=ROOT)

        self.assertEqual(decision["route_kind"], "deep_reasoning")
        self.assertEqual(decision["task_profile"], "deep_reasoning")
        self.assertTrue(decision["escalation_required"])
        self.assertIn("theory", decision["knowledge_layers"])
        self.assertIn("protocol", decision["knowledge_layers"])

    def test_memory_match_has_zero_model_budget(self):
        decision = compile_controller_decision("Kairos 2026-03-08 happened what?", root=ROOT)

        self.assertEqual(decision["route_kind"], "deterministic_memory")
        self.assertEqual(decision["task_profile"], "deterministic")
        self.assertEqual(decision["model_budget"], 0)
        self.assertEqual(decision["knowledge_layers"], ["kairos"])

    def test_code_and_system_changes_have_reviewed_permissions(self):
        code = compile_controller_decision("Fix this Python bug.", root=ROOT)
        upgrade = compile_controller_decision("Run self-upgrade benchmark harness report.", root=ROOT)

        self.assertEqual(code["tool_permission"], "workspace_write_reviewed")
        self.assertEqual(upgrade["tool_permission"], "system_change_reviewed")
        self.assertTrue(code["escalation_required"])
        self.assertTrue(upgrade["escalation_required"])

    def test_world_query_requires_external_evidence(self):
        decision = compile_controller_decision("world events on 2025-03-08", root=ROOT)

        self.assertEqual(decision["route_kind"], "world_query")
        self.assertEqual(decision["knowledge_layers"], ["external_current"])
        self.assertEqual(decision["tool_permission"], "search_read")

    def test_model_input_contains_signals_but_no_answer(self):
        model_input = compile_controller_example_input("What is freedom?", root=ROOT)

        self.assertTrue(model_input["runtime_signals"]["protocol_concept_detected"])
        self.assertNotIn("direct_answer", model_input)
        self.assertNotIn("output", model_input)

    def test_forced_news_uses_search_permission(self):
        decision = compile_controller_decision("Check this topic.", root=ROOT, pipeline_mode="news")

        self.assertEqual(decision["route_kind"], "forced")
        self.assertEqual(decision["pipeline"], "news")
        self.assertEqual(decision["tool_permission"], "search_read")


if __name__ == "__main__":
    unittest.main(verbosity=2)
