import unittest
from pathlib import Path

from services.coordinate_knowledge import (
    coordinate_cards_block,
    coordinate_cards_health,
    evaluate_coordinate_output,
    evaluate_coordinate_grounding,
    select_coordinate_cards,
)
from services.knowledge_manifest import ROOT
from trinity_console import TrinityConsole, _KNOWLEDGE_TRACE_CTX


class CoordinateKnowledgeTests(unittest.TestCase):
    def test_coordinate_cards_health_and_selection(self):
        health = coordinate_cards_health(root=ROOT)
        self.assertTrue(health["ok"], health)
        self.assertGreaterEqual(health["count"], 20)

        cards = select_coordinate_cards(
            "自我升級要點樣減少能力缺口、風險，並留下 harness trace 做 benchmark replay？",
            root=ROOT,
        )

        ids = {card["id"] for card in cards}
        self.assertIn("coordinate.upgrade.value", ids)
        self.assertIn("coordinate.trace.audit", ids)
        self.assertIn("coordinate.replay.regression", ids)

    def test_coordinate_cards_block_is_prompt_ready(self):
        block, cards = coordinate_cards_block(
            "座標說作為知識層要點樣避免變成神諭？",
            root=ROOT,
        )

        self.assertTrue(cards)
        self.assertIn("Coordinate knowledge cards", block)
        self.assertIn("coordinate.anti_oracle", block)

    def test_coordinate_output_eval_scores_system_answer(self):
        result = evaluate_coordinate_output(
            "自我升級要點樣減少能力缺口同留下 trace？",
            "今次升級要講清楚缺口、風險、測試，並寫入 plan、log、episode、trace 方便回歸驗證。",
            root=ROOT,
        )

        self.assertTrue(result["active"])
        self.assertEqual(result["target"], "system_output")
        self.assertEqual(result["input_role"], "routing_only")
        self.assertGreater(result["score"], 0.0)
        self.assertGreater(result["passed_count"], 0)
        self.assertIn(result["coordinate_use"], {"good", "partial"})
        self.assertFalse(result["over_applied"])
        self.assertTrue(result["source_trace_present"])

    def test_coordinate_output_eval_detects_over_application_on_trivial_query(self):
        result = evaluate_coordinate_output(
            "2+2 等於幾？",
            "從座標說角度，呢個問題有隱藏座標同代價落點。",
            root=ROOT,
        )

        self.assertFalse(result["active"])
        self.assertEqual(result["coordinate_use"], "over_applied")
        self.assertTrue(result["over_applied"])

    def test_new_coordinate_cards_cover_core_upgrade_concepts(self):
        cases = {
            "應該繼續加工具定加知識？": "coordinate.framing.trap",
            "用細模型接管 routing 同 schema 可以降低成本嗎？": "coordinate.small.model.delegation",
            "呢個系統賣點可以係咩？": "coordinate.market.translation",
            "世界觀要點樣變成可運行系統？": "coordinate.executable.worldview",
        }

        for query, expected_id in cases.items():
            with self.subTest(query=query):
                ids = {card["id"] for card in select_coordinate_cards(query, root=ROOT)}
                self.assertIn(expected_id, ids)

    def test_coordinate_grounding_alias_keeps_output_target(self):
        result = evaluate_coordinate_grounding(
            "upgrade harness trace",
            "Use plan, log, episode, trace, validator evidence before changing the system.",
            root=ROOT,
        )

        self.assertEqual(result["target"], "system_output")
        self.assertEqual(result["input_role"], "routing_only")

    def test_freedom_selects_coordinate_definition_card(self):
        cards = select_coordinate_cards("咩係自由？", root=ROOT)
        ids = {card["id"] for card in cards}

        self.assertIn("coordinate.freedom.entropy", ids)

        result = evaluate_coordinate_output(
            "咩係自由？",
            "自由係持續嘅物理過程：維持可能性空間，抵抗格式化收窄，並用 FREEDOM_LOSS_ENTROPY=8.19 追蹤熵同代價。",
            root=ROOT,
        )

        self.assertTrue(result["active"])
        self.assertIn("coordinate.freedom.entropy", result["selected_card_ids"])
        self.assertGreater(result["score"], 0.0)

    def test_short_latin_trigger_does_not_match_inside_words(self):
        cards = select_coordinate_cards("This failure should stay ordinary.", root=ROOT)
        ids = {card["id"] for card in cards}
        self.assertNotIn("coordinate.origin.anchor", ids)

    def test_trinity_rag_block_records_coordinate_card_trace(self):
        token = _KNOWLEDGE_TRACE_CTX.set([])
        try:
            console = TrinityConsole.__new__(TrinityConsole)
            console.data_dir = ROOT / "data"
            block = console.rag_block("自我升級要降低缺口並留下 trace", k=1, max_chars=800)
            trace = console.get_knowledge_trace()
        finally:
            _KNOWLEDGE_TRACE_CTX.reset(token)

        self.assertIn("Coordinate knowledge cards", block)
        self.assertTrue(any(entry["source"] == "coordinate_cards" for entry in trace))
        card_entry = next(entry for entry in trace if entry["source"] == "coordinate_cards")
        self.assertTrue(card_entry["hits"][0]["card_id"].startswith("coordinate."))

    def test_knowledge_health_exposes_coordinate_cards(self):
        console = TrinityConsole.__new__(TrinityConsole)
        console.data_dir = ROOT / "data"

        health = console.knowledge_health_summary()

        self.assertTrue(health["coordinate_cards"]["ok"], health)
        self.assertGreaterEqual(health["coordinate_cards"]["count"], 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
