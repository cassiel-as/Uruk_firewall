import json
import tempfile
import unittest
from pathlib import Path

from training.controller_hard_negative_factory import (
    audit_hard_negative_queue,
    build_hard_negative_pairs,
    run_factory,
)
from training.controller_learning_queue import list_records, summary


class ControllerHardNegativeFactoryTests(unittest.TestCase):
    @staticmethod
    def _empty_dataset(root: Path) -> Path:
        return root / "empty.jsonl"

    def test_curated_pairs_declare_distinct_expected_labels(self):
        pairs = build_hard_negative_pairs()

        self.assertGreaterEqual(len(pairs), 20)
        for pair in pairs:
            labels = {
                (item["expected_route"], item["expected_profile"], item["pipeline_mode"])
                for item in pair["members"]
            }
            self.assertGreaterEqual(len(labels), 2, pair["pair_id"])

    def test_factory_writes_only_complete_teacher_verified_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_root = Path(tmp)
            report = run_factory(
                queue_root=queue_root,
                dataset=self._empty_dataset(queue_root),
                limit_pairs=5,
                write=True,
            )
            queue_summary = summary(base=queue_root / "data" / "controller_learning")
            pending = list_records("pending", 100, base=queue_root / "data" / "controller_learning")
            audit = audit_hard_negative_queue(queue_root=queue_root)

        collected = report["stats"].get("collected", 0)
        self.assertEqual(report["stats"].get("pairs_verified"), 5)
        self.assertEqual(collected, 10)
        self.assertEqual(queue_summary["status_counts"], {"pending": collected})
        self.assertTrue(all(item["priority"] == "medium" for item in pending))
        self.assertTrue(all((item.get("provenance") or {}).get("source_split") == "train" for item in pending))
        self.assertTrue(audit["passed"], audit)
        self.assertEqual(audit["pair_count"], 5)

    def test_factory_is_idempotent_without_occurrence_inflation(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_root = Path(tmp)
            dataset = self._empty_dataset(queue_root)
            run_factory(queue_root=queue_root, dataset=dataset, limit_pairs=2, write=True)
            second = run_factory(queue_root=queue_root, dataset=dataset, limit_pairs=2, write=True)
            pending = list_records("pending", 20, base=queue_root / "data" / "controller_learning")

        self.assertEqual(second["stats"].get("duplicate_unchanged"), 4)
        self.assertTrue(all(item["occurrence_count"] == 1 for item in pending))

    def test_pair_audit_detects_missing_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_root = Path(tmp)
            run_factory(
                queue_root=queue_root,
                dataset=self._empty_dataset(queue_root),
                limit_pairs=1,
                write=True,
            )
            pending_dir = queue_root / "data" / "controller_learning" / "pending"
            first = sorted(pending_dir.glob("learn_*.json"))[0]
            record = json.loads(first.read_text(encoding="utf-8"))
            first.unlink()
            audit = audit_hard_negative_queue(queue_root=queue_root)

        self.assertFalse(audit["passed"])
        self.assertEqual(audit["pair_count"], 1)
        self.assertIn("incomplete", " ".join(audit["issues"][0]["errors"]))
        self.assertEqual((record.get("provenance") or {}).get("pair_size"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
