import unittest

from services.local_model_router import select_local_model
from services.task_profiles import get_task_profile


class LocalModelRouterTests(unittest.TestCase):
    def test_deterministic_json_tasks_do_not_call_a_model(self):
        decision = select_local_model("normalize_json")

        self.assertEqual(decision.execution, "deterministic")
        self.assertFalse(decision.escalation_required)

    def test_classification_uses_local_classifier(self):
        decision = select_local_model("classify", "ordinary request")

        self.assertEqual(decision.profile_name, "local_classifier")
        self.assertEqual(decision.model, "qwen2.5:3b")
        self.assertEqual(decision.authority, "routing_only")

    def test_language_work_uses_local_language_worker(self):
        decision = select_local_model("summarize", "ordinary text")

        self.assertEqual(decision.profile_name, "local_language")
        self.assertEqual(decision.model, "qwen3.5:4b")
        self.assertEqual(decision.authority, "worker")
        self.assertEqual(get_task_profile("local_language")["context_window"], 8192)

    def test_protocol_question_cannot_use_simple_local_answer(self):
        decision = select_local_model("answer_simple", "What is freedom?")

        self.assertEqual(decision.execution, "escalate")
        self.assertTrue(decision.escalation_required)

    def test_decision_tasks_require_large_model_path(self):
        decision = select_local_model("safety_decision", "approve action")

        self.assertEqual(decision.execution, "escalate")
        self.assertTrue(decision.escalation_required)

    def test_vision_profile_matches_installed_model_policy(self):
        profile = get_task_profile("vision")

        self.assertEqual(profile["model"], "qwen3-vl:4b")
        self.assertEqual(profile["authority"], "observation_only")
        self.assertGreater(profile["cold_start_timeout_seconds"], profile["timeout_seconds"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
