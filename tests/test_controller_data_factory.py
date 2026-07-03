import tempfile
import unittest
from pathlib import Path

from training.controller_data_factory import audit_factory_queue, generate_variants, run_factory
from training.controller_learning_queue import list_records, review, summary
from training.dataset_builder import build_examples


ROOT = Path(__file__).resolve().parent.parent


class ControllerDataFactoryTests(unittest.TestCase):
    def test_variants_are_generated_from_route_templates(self):
        examples, _ = build_examples()
        example = next(item for item in examples if item["split"] == "train" and item["output"]["route_kind"] == "code_task")
        variants = generate_variants(example, max_per_source=2)

        self.assertEqual(len(variants), 2)
        self.assertTrue(all(example["input"]["user_input"] in item["query"] for item in variants))

    def test_factory_uses_train_only_and_writes_review_gated_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_root = Path(tmp)
            report = run_factory(queue_root=queue_root, limit=12, max_per_source=2, write=True)
            queue_summary = summary(base=queue_root / "data" / "controller_learning")
            pending = list_records("pending", 50, base=queue_root / "data" / "controller_learning")

        self.assertEqual(report["source_split"], "train")
        self.assertGreater(report["stats"].get("collected", 0), 0)
        self.assertEqual(queue_summary["status_counts"], {"pending": report["stats"]["collected"]})
        self.assertTrue(all((item.get("provenance") or {}).get("source_split") == "train" for item in pending))
        self.assertTrue(all(item["status"] == "pending" for item in pending))

    def test_factory_candidate_cannot_be_approved_into_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_root = Path(tmp)
            run_factory(queue_root=queue_root, limit=1, max_per_source=1, write=True)
            base = queue_root / "data" / "controller_learning"
            candidate = list_records("pending", 1, base=base)[0]

            with self.assertRaisesRegex(ValueError, "only be approved into train"):
                review(
                    candidate["candidate_id"],
                    "approved",
                    reviewer="test",
                    split="test",
                    note="must fail",
                    base=base,
                )

    def test_factory_audit_rechecks_current_teacher(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_root = Path(tmp)
            run_factory(queue_root=queue_root, limit=6, max_per_source=1, write=True)
            audit = audit_factory_queue(queue_root=queue_root)

        self.assertTrue(audit["passed"], audit)
        self.assertEqual(audit["checked"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
