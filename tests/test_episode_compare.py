import json
import os
import tempfile
import unittest
from pathlib import Path

from services.episode_compare import compare_episodes, compare_latest, resolve_episode


def _episode(
    episode_id: str,
    *,
    score=None,
    missing_count=0,
    clean=True,
    issues=None,
    trace_docs=None,
    trace_cards=None,
    density_errors=None,
    council_parse_error="",
    voice_error=False,
    cost_metrics=None,
):
    trace_docs = trace_docs or []
    trace_cards = trace_cards or []
    issues = issues or {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    hits = [
        {"doc_id": doc, "card_id": trace_cards[idx] if idx < len(trace_cards) else doc}
        for idx, doc in enumerate(trace_docs)
    ]
    preview = "[節點錯誤] provider failed" if voice_error else "ok"
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "created_at": "2026-06-01T00:00:00",
        "run": {
            "timestamp": "2026-06-01T00:00:00",
            "pipeline_mode": "auto",
            "selected_modes": ["auto"],
            "input": "probe",
            "input_sha256": "same",
            "cost_metrics": cost_metrics or {
                "estimated_model_calls": 1,
                "estimated_api_model_calls": 0,
                "estimated_context_tokens": 100,
                "estimated_cost_class": "low",
            },
        },
        "context": {
            "knowledge": {
                "health": {
                    "clean": clean,
                    "summary": {"issues": issues},
                },
                "trace": [{"source": "unit", "hits": hits}],
            }
        },
        "validators": {
            "output_density_audit": {
                "audit_ran": True,
                "errors": density_errors or [],
            },
            "council_decision": {
                "verdict": "consensus",
                "_parse_error": council_parse_error,
            },
            "coordinate_output_eval": {
                "active": score is not None,
                "score": score,
                "missing_count": missing_count,
                "coordinate_use": "good" if score == 1.0 else "partial",
            },
            "father_paused": False,
        },
        "voices": {
            "father": {"sha256": "f-bad" if voice_error else "f-ok", "preview": preview},
            "son": {"sha256": "s", "preview": "ok"},
            "spirit": {"sha256": "sp", "preview": "ok"},
            "council": {"sha256": "c", "preview": "ok"},
        },
    }


class EpisodeCompareTests(unittest.TestCase):
    def test_compare_detects_validator_and_knowledge_regressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ep_dir = root / "data" / "harness_episodes" / "2026-06-01"
            ep_dir.mkdir(parents=True)
            left = ep_dir / "left.json"
            right = ep_dir / "right.json"
            left.write_text(json.dumps(_episode(
                "left",
                score=1.0,
                missing_count=0,
                clean=True,
                trace_docs=["core.kairos"],
                trace_cards=["coordinate.upgrade.value"],
                cost_metrics={
                    "estimated_model_calls": 1,
                    "estimated_api_model_calls": 0,
                    "estimated_context_tokens": 100,
                    "estimated_cost_class": "low",
                },
            )), encoding="utf-8")
            right.write_text(json.dumps(_episode(
                "right",
                score=0.5,
                missing_count=2,
                clean=False,
                issues={"P0": 0, "P1": 1, "P2": 0, "P3": 0},
                trace_docs=["core.kairos", "theory.coordinate.cards"],
                trace_cards=["coordinate.upgrade.value", "coordinate.trace.audit"],
                density_errors=["audit failed"],
                council_parse_error="no_decision_block",
                voice_error=True,
                cost_metrics={
                    "estimated_model_calls": 4,
                    "estimated_api_model_calls": 2,
                    "estimated_context_tokens": 240,
                    "estimated_cost_class": "high",
                },
            )), encoding="utf-8")

            report = compare_episodes(left, right, root=root)

            self.assertFalse(report["ok"], report)
            self.assertEqual(report["status"], "regressed")
            self.assertIn("knowledge_clean_regressed", report["regressions"])
            self.assertIn("knowledge_P1_increased", report["regressions"])
            self.assertIn("coordinate_score_decreased", report["regressions"])
            self.assertIn("coordinate_missing_increased", report["regressions"])
            self.assertIn("density_errors_increased", report["regressions"])
            self.assertIn("node_errors_introduced", report["regressions"])
            self.assertIn("api_model_calls_increased", report["regressions"])
            self.assertIn("model_calls_increased", report["regressions"])
            self.assertIn("context_tokens_increased", report["regressions"])
            self.assertEqual(report["metrics"]["coordinate_score"]["delta"], -0.5)
            self.assertEqual(report["metrics"]["api_model_calls"]["delta"], 2)
            self.assertIn("theory.coordinate.cards", report["diffs"]["trace_doc_ids"]["added"])

    def test_latest_pair_uses_older_as_left_and_newer_as_right(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ep_dir = root / "data" / "harness_episodes" / "2026-06-01"
            ep_dir.mkdir(parents=True)
            older = ep_dir / "older.json"
            newer = ep_dir / "newer.json"
            older.write_text(json.dumps(_episode("older", score=0.5, missing_count=1)), encoding="utf-8")
            newer.write_text(json.dumps(_episode("newer", score=1.0, missing_count=0)), encoding="utf-8")
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

            report = compare_latest(root=root)

            self.assertEqual(report["left"]["episode_id"], "older")
            self.assertEqual(report["right"]["episode_id"], "newer")
            self.assertTrue(report["ok"], report)
            self.assertIn("coordinate_score_increased", report["improvements"])
            self.assertIn("coordinate_missing_decreased", report["improvements"])

    def test_resolve_episode_accepts_episode_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ep_dir = root / "data" / "harness_episodes" / "2026-06-01"
            ep_dir.mkdir(parents=True)
            path = ep_dir / "stored_name.json"
            path.write_text(json.dumps(_episode("logical-id")), encoding="utf-8")

            self.assertEqual(resolve_episode("logical-id", root=root), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
