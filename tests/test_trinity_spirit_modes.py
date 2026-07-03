import unittest

from trinity_console import NodeConfig, TrinityConsole


class TrinitySpiritModeTests(unittest.TestCase):
    def test_pipeline_execution_names_do_not_use_spirit_mode_labels(self) -> None:
        console = TrinityConsole.__new__(TrinityConsole)
        console.nodes = {
            "father": NodeConfig("father", "openai", "gpt-x"),
            "son": NodeConfig("son", "openai", "gpt-x"),
            "spirit": NodeConfig("spirit", "openai", "gpt-x"),
        }

        self.assertEqual(console._detect_pipeline_execution_mode(), "single_llm")
        self.assertEqual(console._detect_pipeline_mode(), "single_llm")
        hint = console._voice_mode_hint("father")
        self.assertIn("PIPELINE EXECUTION: single_llm", hint)
        self.assertNotIn("PIPELINE MODE: A", hint)

        console.nodes["spirit"] = NodeConfig("spirit", "anthropic", "claude-x")
        self.assertEqual(console._detect_pipeline_execution_mode(), "multi_llm")
        hint = console._voice_mode_hint("spirit")
        self.assertIn("PIPELINE EXECUTION: multi_llm", hint)
        self.assertNotIn("PIPELINE MODE: B", hint)

    def test_runtime_stochastic_gate_can_trigger_rescan(self) -> None:
        meta = {
            "trigger_mode": "NONE",
            "semantic_score": 0,
            "magnitude": 0.0,
            "primary_assumption": "",
        }

        out = TrinityConsole._apply_spirit_stochastic_gate(meta, roll=0.0)

        self.assertEqual(out["trigger_mode"], "STOCHASTIC")
        self.assertTrue(out["_stochastic_fired"])
        self.assertEqual(out["_stochastic_source"], "runtime_rng")
        self.assertTrue(TrinityConsole._should_rescan(out))

    def test_llm_declared_stochastic_is_downgraded_without_runtime_roll(self) -> None:
        meta = {
            "trigger_mode": "STOCHASTIC",
            "semantic_score": 0,
            "magnitude": 0.0,
            "primary_assumption": "model claimed random",
        }

        out = TrinityConsole._apply_spirit_stochastic_gate(meta, roll=1.0)

        self.assertEqual(out["trigger_mode"], "NONE")
        self.assertFalse(out["_stochastic_fired"])
        self.assertEqual(out["_stochastic_source"], "metadata_downgraded_by_runtime_rng")
        self.assertFalse(TrinityConsole._should_rescan(out))

    def test_runtime_stochastic_upgrades_semantic_to_combined_mode(self) -> None:
        meta = {
            "trigger_mode": "SEMANTIC",
            "semantic_score": 2,
            "magnitude": 4.0,
            "primary_assumption": "hidden additive assumption",
        }

        out = TrinityConsole._apply_spirit_stochastic_gate(meta, roll=0.0)

        self.assertEqual(out["trigger_mode"], "STOCHASTIC+SEMANTIC")
        self.assertTrue(TrinityConsole._should_rescan(out))

    def test_semantic_rescan_still_requires_thresholds(self) -> None:
        low = TrinityConsole._apply_spirit_stochastic_gate(
            {
                "trigger_mode": "SEMANTIC",
                "semantic_score": 1,
                "magnitude": 4.0,
                "primary_assumption": "too weak",
            },
            roll=1.0,
        )
        high = TrinityConsole._apply_spirit_stochastic_gate(
            {
                "trigger_mode": "SEMANTIC",
                "semantic_score": 2,
                "magnitude": 4.0,
                "primary_assumption": "strong enough",
            },
            roll=1.0,
        )

        self.assertEqual(low["trigger_mode"], "SEMANTIC")
        self.assertFalse(TrinityConsole._should_rescan(low))
        self.assertEqual(high["trigger_mode"], "SEMANTIC")
        self.assertTrue(TrinityConsole._should_rescan(high))


if __name__ == "__main__":
    unittest.main(verbosity=2)
