import json
import tempfile
import unittest
from pathlib import Path

from services.harness_episode import SCHEMA_VERSION, build_episode, write_episode
from trinity_console import TrinityConsole


class HarnessEpisodeTests(unittest.TestCase):
    def test_write_episode_records_core_trace_and_validators(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            conversation_path = data_dir / "conversation_history" / "2026-05-30" / "trinity_probe.md"
            conversation_path.parent.mkdir(parents=True)
            conversation_path.write_text("# probe\n", encoding="utf-8")
            result = {
                "timestamp": "2026-05-30T12:00:00",
                "input": "Explain CAU-011",
                "pipeline_mode": "firewall",
                "dispatch": {
                    "mode": "firewall",
                    "mode_rationale": "forced",
                    "references": ["KAIROS_CORE.md"],
                    "suggested_data_refs": ["cau:011"],
                },
                "stage1": {"delabeled_input": "Explain CAU-011"},
                "stage2": {"causal_summary": "summary"},
                "stage3": {"filter_verdict": "STRONG"},
                "father": "father output",
                "son": "son output",
                "spirit": "spirit output",
                "council": "council output",
                "output_density_audit": {"audit_ran": True, "density": 0.8},
                "council_decision": {"verdict": "consensus"},
                "coordinate_output_eval": {
                    "active": True,
                    "target": "system_output",
                    "score": 1.0,
                    "selected_count": 1,
                    "passed_count": 1,
                },
                "son_veto_metadata": {"veto_type": "none"},
                "spirit_metadata": {"trigger_mode": "NONE"},
                "cost_metrics": {
                    "route_kind": "self_upgrade",
                    "tier": "desktop_or_strong",
                    "estimated_model_calls": 2,
                    "estimated_api_model_calls": 0,
                    "estimated_context_tokens": 120,
                    "estimated_cost_class": "low",
                },
                "context_budget": {
                    "route_kind": "self_upgrade",
                    "max_context_tokens": 9000,
                    "estimated_total_tokens": 120,
                },
                "inference_usage": {
                    "actual_requests": 3,
                    "successful_requests": 3,
                    "failed_requests": 0,
                    "unique_model_count": 2,
                    "unique_models": ["groq/a", "openrouter/b"],
                },
                "model_tier": "desktop_or_strong",
                "escalation_level": 3,
                "node_config": {"council": "groq/llama"},
                "knowledge_trace": [
                    {
                        "source": "rag_block",
                        "query_sha256": "abc",
                        "hits": [{"doc_id": "core.kairos", "source_file": "data/core/KAIROS_CORE.md"}],
                    }
                ],
                "knowledge_health": {
                    "clean": True,
                    "summary": {"issues": {"P0": 0, "P1": 0, "P2": 0, "P3": 0}},
                },
            }

            out_path = write_episode(
                result,
                data_dir=data_dir,
                conversation_path=conversation_path,
            )

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
            self.assertEqual(payload["episode_id"], "trinity_probe")
            self.assertEqual(
                payload["artifacts"]["conversation_markdown"],
                "conversation_history/2026-05-30/trinity_probe.md",
            )
            self.assertEqual(payload["context"]["dispatch"]["mode"], "firewall")
            self.assertEqual(payload["stages"]["stage3"]["filter_verdict"], "STRONG")
            self.assertTrue(payload["validators"]["output_density_audit"]["audit_ran"])
            self.assertTrue(payload["validators"]["density_audit"]["audit_ran"])
            self.assertEqual(payload["validators"]["council_decision"]["verdict"], "consensus")
            self.assertTrue(payload["validators"]["coordinate_output_eval"]["active"])
            self.assertEqual(payload["validators"]["coordinate_output_eval"]["target"], "system_output")
            self.assertEqual(payload["validators"]["coordinate_output_eval"]["score"], 1.0)
            self.assertEqual(payload["validators"]["coordinate_eval"]["score"], 1.0)
            self.assertEqual(payload["run"]["cost_metrics"]["estimated_api_model_calls"], 0)
            self.assertEqual(payload["run"]["context_budget"]["route_kind"], "self_upgrade")
            self.assertEqual(payload["run"]["model_tier"], "desktop_or_strong")
            self.assertEqual(payload["run"]["inference_usage"]["actual_requests"], 3)
            self.assertEqual(payload["run"]["inference_usage"]["unique_model_count"], 2)
            self.assertEqual(payload["context"]["dispatch"]["cost_metrics"]["estimated_model_calls"], 2)
            self.assertIn("sha256", payload["voices"]["council"])
            self.assertEqual(
                payload["context"]["knowledge"]["trace"][0]["hits"][0]["doc_id"],
                "core.kairos",
            )
            self.assertTrue(payload["context"]["knowledge"]["health"]["clean"])

    def test_build_episode_bounds_large_voice_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            conversation_path = data_dir / "conversation_history" / "2026-05-30" / "trinity_large.md"
            long_text = "x" * 9000

            payload = build_episode(
                {"timestamp": "now", "input": "q", "council": long_text},
                data_dir=data_dir,
                conversation_path=conversation_path,
            )

            council = payload["voices"]["council"]
            self.assertEqual(council["preview"]["original_chars"], 9000)
            self.assertTrue(council["preview"]["truncated"])
            self.assertEqual(len(council["preview"]["text_preview"]), 4000)

    def test_save_kairos_writes_harness_episode_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            console = TrinityConsole.__new__(TrinityConsole)
            console.data_dir = Path(tmp)
            result = {
                "timestamp": "2026-05-30T12:00:00",
                "input": "probe",
                "dispatch": {"mode": "auto", "references": []},
                "father": "f",
                "son": "s",
                "spirit": "sp",
                "council": "c",
                "node_config": {},
            }

            path = console.save_kairos(result, label="unit")
            episode_path = console.data_dir / "harness_episodes" / path.parent.name / f"{path.stem}.json"

            self.assertTrue(path.exists())
            self.assertTrue(episode_path.exists())
            payload = json.loads(episode_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["episode_id"], path.stem)
            self.assertEqual(result["harness_episode"], episode_path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
