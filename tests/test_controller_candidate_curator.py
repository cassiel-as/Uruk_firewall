import json
import tempfile
import unittest
from pathlib import Path

from training.controller_candidate_curator import (
    apply_review_packet,
    audit_review_packet,
    prepare_review_packet,
)
from training.controller_data_factory import run_factory as run_rewrite_factory
from training.controller_hard_negative_factory import run_factory as run_hard_negative_factory
from training.controller_learning_queue import list_records


class ControllerCandidateCuratorTests(unittest.TestCase):
    @staticmethod
    def _empty_dataset(root: Path) -> Path:
        return root / "empty.jsonl"

    def test_prepare_keeps_hard_negative_pairs_atomic_and_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_hard_negative_factory(
                queue_root=root,
                dataset=self._empty_dataset(root),
                limit_pairs=2,
                write=True,
            )
            run_rewrite_factory(queue_root=root, limit=4, write=True)
            packet = prepare_review_packet(base=root / "data" / "controller_learning", max_candidates=4)

        self.assertEqual(packet["selection_summary"]["candidate_count"], 4)
        self.assertTrue(all(unit["unit_type"] == "hard_negative_pair" for unit in packet["units"]))
        self.assertTrue(all(unit["candidate_count"] == 2 for unit in packet["units"]))
        self.assertTrue(all(unit["decision"] == "pending" for unit in packet["units"]))

    def test_prepare_surfaces_encoding_blocker_for_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_rewrite_factory(queue_root=root, limit=1, write=True)
            pending = root / "data" / "controller_learning" / "pending"
            path = next(pending.glob("learn_*.json"))
            record = json.loads(path.read_text(encoding="utf-8"))
            record["input"]["user_input"] = "bad \ue000 text"
            record["input"]["runtime_signals"]["text_length"] = len("bad \ue000 text")
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            packet = prepare_review_packet(base=root / "data" / "controller_learning", max_candidates=1)

        unit = packet["units"][0]
        self.assertEqual(unit["recommended_action"], "reject")
        self.assertIn("encoding.private_use_chars", unit["blockers"])

    def test_apply_moves_complete_approved_pair_only_after_explicit_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "data" / "controller_learning"
            run_hard_negative_factory(
                queue_root=root,
                dataset=self._empty_dataset(root),
                limit_pairs=1,
                write=True,
            )
            packet = prepare_review_packet(base=base, max_candidates=2)
            pending_result = apply_review_packet(packet, reviewer="test", base=base)
            packet["units"][0]["decision"] = "approved"
            approved_result = apply_review_packet(packet, reviewer="test", base=base)
            approved = list_records("approved", 10, base=base)

        self.assertEqual(pending_result["applied_count"], 0)
        self.assertEqual(approved_result["applied_count"], 2)
        self.assertEqual(len(approved), 2)

    def test_audit_detects_candidate_that_is_no_longer_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "data" / "controller_learning"
            run_hard_negative_factory(
                queue_root=root,
                dataset=self._empty_dataset(root),
                limit_pairs=1,
                write=True,
            )
            packet = prepare_review_packet(base=base, max_candidates=2)
            packet["units"][0]["decision"] = "approved"
            apply_review_packet(packet, reviewer="test", base=base)
            audit = audit_review_packet(packet, base=base)

        self.assertFalse(audit["passed"])
        self.assertIn("no longer pending", " ".join(audit["issues"][0]["errors"]))

    def test_audit_rejects_partial_hard_negative_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "data" / "controller_learning"
            run_hard_negative_factory(
                queue_root=root,
                dataset=self._empty_dataset(root),
                limit_pairs=1,
                write=True,
            )
            packet = prepare_review_packet(base=base, max_candidates=2)
            unit = packet["units"][0]
            unit["candidate_ids"] = unit["candidate_ids"][:1]
            unit["members"] = unit["members"][:1]
            unit["candidate_count"] = 1
            audit = audit_review_packet(packet, base=base)

        self.assertFalse(audit["passed"])
        self.assertIn("differs from current pending pair", " ".join(audit["issues"][0]["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
