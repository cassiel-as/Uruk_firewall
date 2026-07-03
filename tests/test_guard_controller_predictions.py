import json
import tempfile
import unittest
from pathlib import Path

from training.dataset_builder import write_dataset
from training.dataset_validator import iter_jsonl
from training.guard_controller_predictions import guard_predictions


class GuardControllerPredictionsTests(unittest.TestCase):
    def _write_predictions(self, dataset: Path, output: Path, *, wrong_routes: bool) -> None:
        rows = []
        changed_permission = False
        for _, example in iter_jsonl(dataset / "test.jsonl"):
            decision = dict(example["output"])
            if wrong_routes:
                decision["route_kind"] = "small_task"
            elif not changed_permission and decision["tool_permission"] != "none":
                decision["tool_permission"] = "none"
                changed_permission = True
            rows.append({"example_id": example["example_id"], "output": decision})
        output.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_guard_overrides_policy_fields_without_hiding_valid_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset"
            predictions = root / "raw.jsonl"
            guarded = root / "guarded.jsonl"
            write_dataset(dataset)
            self._write_predictions(dataset, predictions, wrong_routes=False)

            report = guard_predictions(
                dataset=dataset,
                predictions=predictions,
                output=guarded,
                split="test",
            )

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["route_acceptance_rate"], 1.0)
        self.assertGreaterEqual(report["override_counts"].get("tool_permission", 0), 1)

    def test_guarded_benchmark_does_not_qualify_low_route_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset"
            predictions = root / "raw.jsonl"
            guarded = root / "guarded.jsonl"
            write_dataset(dataset)
            self._write_predictions(dataset, predictions, wrong_routes=True)

            report = guard_predictions(
                dataset=dataset,
                predictions=predictions,
                output=guarded,
                split="test",
            )

        self.assertFalse(report["passed"])
        self.assertFalse(report["guard_gates"]["route_acceptance"])
        self.assertGreater(report["fallback_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
