import tempfile
import unittest
from pathlib import Path

from services.prompt_regression import (
    collect_prompt_files,
    fingerprint_prompt_bundle,
    run_prompt_regression_check,
    write_prompt_baseline,
)


class PromptRegressionTests(unittest.TestCase):
    def _make_root(self, base: Path) -> None:
        (base / "config" / "prompts").mkdir(parents=True)
        (base / "config" / "protocol" / "references").mkdir(parents=True)
        (base / "services").mkdir()
        (base / "data").mkdir()
        (base / "config" / "prompts" / "father.txt").write_text("father prompt", encoding="utf-8")
        (base / "config" / "prompts" / "father.txt.v8.bak").write_text("old prompt", encoding="utf-8")
        (base / "config" / "protocol" / "SKILL.md").write_text("skill prompt", encoding="utf-8")
        (base / "config" / "protocol" / "references" / "trinity.md").write_text("trinity", encoding="utf-8")
        (base / "services" / "relay_protocol.py").write_text("def contract(): return 'x'\n", encoding="utf-8")

    def test_collect_prompt_files_excludes_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_root(root)

            paths = [path.name for path in collect_prompt_files(root=root)]

            self.assertIn("father.txt", paths)
            self.assertNotIn("father.txt.v8.bak", paths)
            self.assertIn("relay_protocol.py", paths)

    def test_baseline_detects_prompt_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_root(root)
            baseline = root / "data" / "prompt_regression_baseline.json"

            write_prompt_baseline(root=root, path=baseline, label="unit")
            first = run_prompt_regression_check(
                root=root,
                baseline_path=baseline,
                run_benchmark=False,
                run_quick_eval=False,
            )
            self.assertTrue(first["ok"], first)
            self.assertFalse(first["diff"]["prompt_changed"], first)

            (root / "config" / "prompts" / "father.txt").write_text("father prompt changed", encoding="utf-8")
            second = run_prompt_regression_check(
                root=root,
                baseline_path=baseline,
                run_benchmark=False,
                run_quick_eval=False,
            )

            self.assertTrue(second["ok"], second)
            self.assertTrue(second["diff"]["prompt_changed"], second)
            self.assertIn("config/prompts/father.txt", second["diff"]["changed"])
            self.assertIn("prompt_bundle_changed", second["changes"])

    def test_update_baseline_resets_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_root(root)
            baseline = root / "data" / "prompt_regression_baseline.json"
            (root / "config" / "prompts" / "father.txt").write_text("new current", encoding="utf-8")

            report = run_prompt_regression_check(
                root=root,
                baseline_path=baseline,
                update_baseline=True,
                run_benchmark=False,
                run_quick_eval=False,
            )

            self.assertTrue(report["baseline_written"], report)
            self.assertFalse(report["diff"]["prompt_changed"], report)
            self.assertEqual(
                report["fingerprint"]["sha256"],
                fingerprint_prompt_bundle(root=root)["sha256"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
