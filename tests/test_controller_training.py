import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from training.benchmark_controller import run_benchmark
from training.dataset_builder import build_examples, write_dataset
from training.dataset_validator import dataset_paths, validate_dataset, validate_example


class ControllerTrainingTests(unittest.TestCase):
    def test_builder_creates_strict_privacy_gated_examples(self):
        examples, meta = build_examples()

        self.assertGreaterEqual(len(examples), 50)
        self.assertEqual(meta["build_issues"], [])
        self.assertEqual(meta["source_stats"].get("approved_episodes_loaded", 0), 0)
        self.assertGreaterEqual(meta["source_stats"]["episodes_skipped_not_approved"], 1)
        self.assertTrue(all(validate_example(example) == [] for example in examples))
        serialized = json.dumps(examples, ensure_ascii=False)
        self.assertNotIn('"direct_answer"', serialized)
        self.assertNotIn('"voices"', serialized)
        self.assertNotIn('"council"', serialized)

    def test_written_dataset_validates_and_baseline_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            manifest = write_dataset(output_dir)
            validation = validate_dataset(dataset_paths(output_dir))
            benchmark = run_benchmark(output_dir)

        self.assertGreaterEqual(manifest["example_count"], 50)
        self.assertTrue(validation["passed"], validation)
        self.assertTrue(benchmark["passed"], benchmark)
        self.assertEqual(benchmark["metrics"]["route_accuracy"], 1.0)
        self.assertEqual(benchmark["metrics"]["high_risk_false_local_rate"], 0.0)

    def test_benchmark_rejects_high_risk_false_local_candidate(self):
        examples, _ = build_examples()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            predictions_path = output_dir / "predictions.jsonl"
            lines = []
            for example in examples:
                output = dict(example["output"])
                if (example["input"]["runtime_signals"]).get("protocol_concept_detected"):
                    output["route_kind"] = "small_task"
                    output["task_profile"] = "local_language"
                    output["knowledge_layers"] = []
                    output["model_budget"] = 1
                    output["escalation_required"] = False
                    output["reason_codes"] = ["route.small_task", "policy.local_worker_allowed"]
                lines.append(json.dumps({"example_id": example["example_id"], "output": output}, ensure_ascii=False))
            predictions_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            write_dataset(output_dir / "dataset")
            benchmark = run_benchmark(output_dir / "dataset", predictions_path=predictions_path)

        self.assertFalse(benchmark["passed"])
        self.assertGreater(benchmark["metrics"]["high_risk_false_local_rate"], 0)
        self.assertGreater(benchmark["metrics"]["abstract_missed_escalation_rate"], 0)

    def test_benchmark_rejects_wrong_protected_tool_permission(self):
        examples, _ = build_examples()
        target = next(
            example
            for example in examples
            if example["output"]["tool_permission"] == "workspace_write_reviewed"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            dataset_dir = output_dir / "dataset"
            write_dataset(dataset_dir)
            output = dict(target["output"])
            output["tool_permission"] = "read_only"
            predictions_path = output_dir / "predictions.jsonl"
            predictions_path.write_text(
                json.dumps({"example_id": target["example_id"], "output": output}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            benchmark = run_benchmark(
                dataset_dir,
                predictions_path=predictions_path,
                example_ids={target["example_id"]},
            )

        self.assertFalse(benchmark["passed"])
        self.assertFalse(benchmark["gates"]["tool_permission_accuracy"])
        self.assertFalse(benchmark["gates"]["protected_permission_recall"])

    def test_empty_error_rate_denominators_are_zero(self):
        examples, _ = build_examples()
        example_id = examples[0]["example_id"]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            write_dataset(output_dir / "dataset")
            prediction = next(example["output"] for example in examples if example["example_id"] == example_id)
            predictions_path = output_dir / "predictions.jsonl"
            predictions_path.write_text(
                json.dumps({"example_id": example_id, "output": prediction}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            benchmark = run_benchmark(
                output_dir / "dataset",
                predictions_path=predictions_path,
                example_ids={example_id},
            )

        self.assertEqual(benchmark["metrics"]["abstract_missed_escalation_rate"], 0.0)

    def test_validator_allows_same_query_with_different_pipeline_mode(self):
        examples, _ = build_examples()
        first = deepcopy(examples[0])
        second = deepcopy(first)
        second["example_id"] = "ctrl_1111111111111111"
        second["input"]["runtime_signals"]["pipeline_mode"] = "news"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.jsonl"
            path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in (first, second)) + "\n",
                encoding="utf-8",
            )
            validation = validate_dataset([path])

        self.assertTrue(validation["passed"], validation)

    def test_validator_rejects_same_query_with_same_routing_signals(self):
        examples, _ = build_examples()
        first = deepcopy(examples[0])
        second = deepcopy(first)
        second["example_id"] = "ctrl_2222222222222222"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.jsonl"
            path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in (first, second)) + "\n",
                encoding="utf-8",
            )
            validation = validate_dataset([path])

        self.assertFalse(validation["passed"])
        self.assertIn("duplicate query and routing signals", validation["issues"][0]["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
