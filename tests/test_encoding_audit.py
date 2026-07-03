import tempfile
import unittest
from pathlib import Path

from services.encoding_audit import analyze_text, audit_encoding


class EncodingAuditTests(unittest.TestCase):
    def test_clean_text_has_no_issues(self):
        report = analyze_text("自由是一個持續的物理過程。\n")

        self.assertEqual(report["issues"], [])
        self.assertFalse(report["latin1_utf8_repair_possible"])

    def test_detects_latin1_utf8_mojibake(self):
        corrupted = "\u00e2\x9c\x85 \u00e5\x8d\x87\u00e7\u00b4\x9a\u00e5\xae\x8c\u00e6\x88\x90"
        report = analyze_text(corrupted)

        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("c1_control_chars", codes)
        self.assertIn("mojibake_markers", codes)
        self.assertTrue(report["latin1_utf8_repair_possible"])

    def test_audit_encoding_scans_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clean.md").write_text("clean text\n", encoding="utf-8")
            (root / "bad.json").write_text(
                '{"summary":"\u00e2\x9c\x85 \u00e5\x8d\x87\u00e7\u00b4\x9a"}',
                encoding="utf-8",
            )

            report = audit_encoding(root=root)

            self.assertEqual(report["file_count"], 2)
            self.assertEqual(report["flagged_count"], 1)
            self.assertFalse(report["clean"])
            self.assertEqual(report["files"][0]["path"], "bad.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
