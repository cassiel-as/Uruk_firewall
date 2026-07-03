import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from services.runtime_summary_indexes import (  # noqa: E402
    build_all,
    build_experiment_index,
    build_harness_episode_index,
    build_upgrade_history_index,
)


class RuntimeSummaryIndexTests(unittest.TestCase):
    def test_build_all_in_memory_returns_three_indexes(self):
        outputs = build_all(ROOT, write=False)

        self.assertIn("data/index/EXPERIMENT_INDEX.md", outputs)
        self.assertIn("data/index/HARNESS_EPISODE_INDEX.md", outputs)
        self.assertIn("data/index/UPGRADE_HISTORY_INDEX.md", outputs)
        for content in outputs.values():
            self.assertGreater(len(content), 500)

    def test_experiment_index_summarizes_raw_experiment_files(self):
        text = build_experiment_index(ROOT)

        self.assertIn("# URUK Experiment Summary Index", text)
        self.assertIn("EXPERIMENT_011_FULL", text)
        self.assertIn("classification:", text)
        self.assertIn("conclusion_preview:", text)

    def test_harness_index_summarizes_episode_metadata(self):
        text = build_harness_episode_index(ROOT)

        self.assertIn("# URUK Harness Episode Summary Index", text)
        self.assertIn("Pipeline modes:", text)
        self.assertIn("coordinate_output_eval:", text)
        self.assertIn("data/harness_episodes/", text)

    def test_upgrade_index_summarizes_plans_reports_and_logs(self):
        text = build_upgrade_history_index(ROOT)

        self.assertIn("# URUK Self-Upgrade History Index", text)
        self.assertIn("Plan statuses:", text)
        self.assertIn("Recent Plans", text)
        self.assertIn("upgrade-20260602-132159-22c2dd", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
