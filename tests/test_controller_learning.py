import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.controller_learning import accumulate_learning_candidate, sanitize_controller_input
from services.controller_policy import compile_controller_decision, compile_controller_example_input
from training.controller_learning_queue import list_records, review, summary
from training.dataset_builder import build_examples


ROOT = Path(__file__).resolve().parent.parent


class ControllerLearningTests(unittest.TestCase):
    def _case(self, query: str = "Open browser and inspect the page."):
        reference = compile_controller_decision(query, root=ROOT)
        model_input = compile_controller_example_input(query, root=ROOT)
        candidate = dict(reference)
        candidate["route_kind"] = "small_task"
        candidate["task_profile"] = "local_language"
        candidate["knowledge_layers"] = []
        candidate["model_budget"] = 1
        candidate["tool_permission"] = "none"
        candidate["escalation_required"] = False
        candidate["reason_codes"] = ["route.small_task", "policy.local_worker_allowed"]
        comparison = {
            "schema_valid": True,
            "schema_errors": [],
            "route_match": False,
            "authority_match": False,
            "escalation_match": False,
            "exact_match": False,
            "differences": {"route_kind": {"reference": "tool_task", "candidate": "small_task"}},
        }
        return model_input, reference, candidate, comparison

    def test_sanitizer_redacts_direct_identifiers_but_keeps_date(self):
        text, redactions = sanitize_controller_input(
            "Email me@example.com key=abcd1234 at C:\\Users\\alice\\secret.txt on 2026-03-08"
        )

        self.assertNotIn("me@example.com", text)
        self.assertNotIn("alice", text)
        self.assertNotIn("abcd1234", text)
        self.assertIn("2026-03-08", text)
        self.assertIn("email", redactions)
        self.assertIn("secret_assignment", redactions)

    def test_disagreement_is_collected_and_deduplicated(self):
        model_input, reference, candidate, comparison = self._case()
        config = {"learning_queue_enabled": True, "agreement_sample_rate": 0.0, "max_records_per_day": 10}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = accumulate_learning_candidate(
                model_input["user_input"],
                root=root,
                model_input=model_input,
                reference=reference,
                candidate=candidate,
                comparison=comparison,
                config=config,
            )
            second = accumulate_learning_candidate(
                model_input["user_input"],
                root=root,
                model_input=model_input,
                reference=reference,
                candidate=candidate,
                comparison=comparison,
                config=config,
            )
            queue_summary = summary(base=root / "data" / "controller_learning")

        self.assertEqual(first["status"], "collected")
        self.assertEqual(first["priority"], "critical")
        self.assertEqual(second["status"], "duplicate_updated")
        self.assertEqual(queue_summary["record_count"], 1)
        self.assertEqual(queue_summary["occurrence_count"], 2)

    def test_review_approval_moves_case_and_builder_can_include_it(self):
        query = "Open browser and inspect the page."
        model_input, reference, candidate, comparison = self._case(query)
        config = {"learning_queue_enabled": True, "agreement_sample_rate": 0.0, "max_records_per_day": 10}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collected = accumulate_learning_candidate(
                query,
                root=root,
                model_input=model_input,
                reference=reference,
                candidate=candidate,
                comparison=comparison,
                config=config,
            )
            base = root / "data" / "controller_learning"
            approved = review(
                collected["candidate_id"],
                "approved",
                reviewer="test",
                split="train",
                note="reviewed",
                base=base,
            )
            with patch("training.dataset_builder.APPROVED_LEARNING_DIR", base / "approved"):
                examples, meta = build_examples()
            approved_count = len(list_records("approved", 10, base=base))

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved_count, 1)
        self.assertGreaterEqual(meta["source_stats"].get("approved_learning_candidates_loaded", 0), 1)
        self.assertTrue(any(example["source"]["kind"] == "approved_shadow" for example in examples))

    def test_factory_daily_limit_does_not_consume_shadow_limit(self):
        model_input, reference, candidate, comparison = self._case()
        config = {"learning_queue_enabled": True, "agreement_sample_rate": 1.0, "max_records_per_day": 1}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            factory = accumulate_learning_candidate(
                "Factory variant: " + model_input["user_input"],
                root=root,
                model_input={
                    **model_input,
                    "user_input": "Factory variant: " + model_input["user_input"],
                    "runtime_signals": {
                        **model_input["runtime_signals"],
                        "text_length": len("Factory variant: " + model_input["user_input"]),
                    },
                },
                reference=reference,
                candidate=reference,
                comparison={**comparison, "route_match": True, "authority_match": True, "escalation_match": True, "differences": {}},
                config=config,
                provenance={"type": "data_factory", "source_split": "train"},
                force_collect=True,
            )
            shadow = accumulate_learning_candidate(
                model_input["user_input"],
                root=root,
                model_input=model_input,
                reference=reference,
                candidate=candidate,
                comparison=comparison,
                config=config,
            )

        self.assertEqual(factory["status"], "collected")
        self.assertEqual(shadow["status"], "collected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
