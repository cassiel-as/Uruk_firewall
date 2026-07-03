import tempfile
import unittest
from pathlib import Path

from density_audit import DensityAuditor


class DensityAuditPostureTests(unittest.TestCase):
    def test_operator_text_routes_feedback_but_audit_target_is_system_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            auditor = DensityAuditor(Path(tmp))
            session = {
                "timestamp": "2026-05-31T10:00:00",
                "input": "you missed the canonical update",
                "dispatch": {"mode": "auto", "references": []},
                "father": "",
                "son": "",
                "spirit": "",
                "council": "I missed the output boundary and should correct the answer.",
            }

            result = auditor.run_audit(session).to_dict()

        self.assertEqual(result["audit_target"], "system_output")
        self.assertEqual(result["input_role"], "routing_and_operator_feedback_only")
        self.assertTrue(result["audit_ran"])
        sources = {
            hit["source"]
            for candidate in result["candidates"]
            for hit in candidate["hits"]
        }
        self.assertIn("operator_feedback", sources)
        self.assertIn("operator_instruction", sources)
        self.assertNotIn("input", sources)

    def test_generic_qna_does_not_become_kairos_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            auditor = DensityAuditor(Path(tmp))
            session = {
                "timestamp": "2026-06-02T10:00:00",
                "input": "Python 係咩",
                "dispatch": {"mode": "auto", "references": []},
                "father": "Python is a programming language, not a new protocol for URUK.",
                "son": "",
                "spirit": "",
                "council": "Python is a language. This is ordinary Q&A.",
            }

            result = auditor.run_audit(session).to_dict()

            self.assertEqual(result["density"], "LOW")
            self.assertIsNone(result["proposed_path"])
            self.assertTrue(result["candidates"])
            self.assertTrue(all(c["rejected"] for c in result["candidates"]))
            self.assertTrue(
                any("ordinary Q&A" in (c["rejection_reason"] or "") for c in result["candidates"]),
                result["candidates"],
            )
            self.assertFalse((Path(tmp) / "kairos" / "KAIROS_ACTIVE.md").exists())
            self.assertFalse((Path(tmp) / "kairos" / "KAIROS_LOG_UPDATED_v8.md").exists())

    def test_short_system_concept_question_is_still_not_kairos_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            auditor = DensityAuditor(Path(tmp))
            session = {
                "timestamp": "2026-06-02T10:30:00",
                "input": "Kairos 係咩",
                "dispatch": {"mode": "auto", "references": ["kairos:active"]},
                "father": "Kairos is not a new protocol in this answer; it is the memory layer.",
                "son": "",
                "spirit": "",
                "council": "This is an explanatory answer, not a system change.",
            }

            result = auditor.run_audit(session).to_dict()

            self.assertEqual(result["density"], "LOW")
            self.assertIsNone(result["proposed_path"])
            self.assertTrue(result["candidates"])
            self.assertTrue(all(c["rejected"] for c in result["candidates"]))

    def test_canonical_change_writes_proposal_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            auditor = DensityAuditor(Path(tmp))
            session = {
                "timestamp": "2026-06-02T11:00:00",
                "input": "從而家開始 canonical: Kairos active memory must be operator-reviewed only",
                "dispatch": {"mode": "auto", "references": ["kairos:active"]},
                "father": "The system memory rule changed and should be recorded as a proposal.",
                "son": "",
                "spirit": "",
                "council": "Accepted as proposed protocol posture pending operator review.",
            }

            result = auditor.run_audit(session).to_dict()

            self.assertEqual(result["density"], "HIGH")
            self.assertIsNotNone(result["proposed_path"])
            self.assertIn("kairos/_proposed/KAIROS_PROPOSED_", result["proposed_path"])
            proposed = Path(tmp).parent / result["proposed_path"]
            self.assertTrue(proposed.exists(), result["proposed_path"])
            self.assertIn("CANONICAL: false", proposed.read_text(encoding="utf-8"))
            self.assertFalse((Path(tmp) / "kairos" / "KAIROS_ACTIVE.md").exists())
            self.assertFalse((Path(tmp) / "kairos" / "KAIROS_LOG_UPDATED_v8.md").exists())

    def test_read_only_memory_recall_does_not_write_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            auditor = DensityAuditor(Path(tmp))
            session = {
                "timestamp": "2026-06-02T11:30:00",
                "input": "3月8號發生過咩事？",
                "dispatch": {
                    "mode": "kairos_memory_direct",
                    "references": [
                        "data/kairos/KAIROS_ARCHIVE_INDEX.md",
                        "data/kairos/KAIROS_LOG_UPDATED_v8.md",
                    ],
                },
                "father": "",
                "son": "",
                "spirit": "",
                "council": (
                    "3月8號指向 KAIROS_LOG_004, PHYSICS_CONSTANTS.md, "
                    "CIVILIZATION_ANCHORS.md, KAIROS_ARCHIVE_INDEX.md, "
                    "KAIROS_LOG_UPDATED_v8.md, and CAUSAL_DATABASE."
                ),
                "suppress_density_proposal": True,
            }

            result = auditor.run_audit(session).to_dict()

            self.assertEqual(result["density"], "HIGH")
            self.assertIsNone(result["proposed_path"])
            self.assertIn("proposal_write_suppressed", result["warnings"])
            proposed_dir = Path(tmp) / "kairos" / "_proposed"
            self.assertFalse(proposed_dir.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
