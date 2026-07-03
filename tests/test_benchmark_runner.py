import unittest

from tools.benchmark_runner import run_cases


class BenchmarkRunnerTests(unittest.TestCase):
    def test_coordinate_foundation_benchmark_passes(self):
        report = run_cases()

        self.assertTrue(report["passed"], report)
        self.assertGreaterEqual(report["case_count"], 10)
        self.assertEqual(report["failed_count"], 0)
        self.assertIn("cost_summary", report)
        self.assertIn("estimated_model_calls", report["cost_summary"])
        self.assertIn("cost_metrics", report["results"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
