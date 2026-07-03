import unittest
from pathlib import Path

from services.cost_aware_router import route_query


ROOT = Path(__file__).resolve().parent.parent


class CostAwareRouterTests(unittest.TestCase):
    def test_kairos_memory_uses_zero_model_direct_route(self):
        result = route_query("Kairos 2026-03-08 happened what?", root=ROOT)

        self.assertEqual(result["route_kind"], "deterministic_memory")
        self.assertEqual(result["short_circuit"], "kairos_memory_direct")
        self.assertEqual(result["cost_metrics"]["estimated_model_calls"], 0)
        self.assertEqual(result["cost_metrics"]["estimated_cost_class"], "zero")
        self.assertIn("2026-03-08", result["direct_answer"])

    def test_world_date_query_does_not_use_kairos_memory(self):
        result = route_query("world events on 2026-03-08", root=ROOT)

        self.assertEqual(result["route_kind"], "world_query")
        self.assertIsNone(result.get("direct_answer"))
        self.assertEqual(result["recommended_pipeline_mode"], "news")

    def test_explicit_not_kairos_world_date_uses_news_route(self):
        result = route_query("2026年3月8號有咩世界大事？唔係 Kairos。", root=ROOT)

        self.assertEqual(result["route_kind"], "world_query")
        self.assertIsNone(result.get("direct_answer"))
        self.assertEqual(result["recommended_pipeline_mode"], "news")

    def test_cantonese_current_world_query_uses_news_route(self):
        result = route_query("今日發生咩世界大事", root=ROOT)

        self.assertEqual(result["route_kind"], "world_query")
        self.assertEqual(result["recommended_pipeline_mode"], "news")

    def test_recent_fed_rate_query_uses_news_route(self):
        result = route_query(
            "As of today, what was the Federal Reserve's most recent interest rate decision?",
            root=ROOT,
        )

        self.assertEqual(result["route_kind"], "world_query")
        self.assertEqual(result["recommended_pipeline_mode"], "news")

    def test_cantonese_recent_fed_rate_query_uses_news_route(self):
        result = route_query(
            "今日係 2026 年 6 月 25 日。美聯儲最近嘅利率決定對座標說點理解？",
            root=ROOT,
        )

        self.assertEqual(result["route_kind"], "world_query")
        self.assertEqual(result["recommended_pipeline_mode"], "news")

    def test_ambiguous_month_day_uses_scope_clarification_route(self):
        result = route_query("3月8號發生過咩？", root=ROOT)

        self.assertEqual(result["route_kind"], "deterministic_memory")
        self.assertEqual(result["short_circuit"], "date_scope_clarification")
        self.assertEqual(result["recommended_pipeline_mode"], "date_scope_clarification")
        self.assertIn("Kairos", result["direct_answer"])
        self.assertIn("世界大事", result["direct_answer"])

    def test_self_upgrade_skips_pre_gate(self):
        result = route_query("self-upgrade benchmark harness report", root=ROOT)

        self.assertEqual(result["route_kind"], "self_upgrade")
        self.assertTrue(result["skip_pre_gate"])
        self.assertEqual(result["cost_metrics"]["estimated_api_model_calls"], 0)

    def test_cantonese_self_upgrade_action_uses_upgrade_route(self):
        result = route_query("執行自我升級", root=ROOT)

        self.assertEqual(result["route_kind"], "self_upgrade")
        self.assertTrue(result["skip_pre_gate"])

    def test_short_ordinary_query_uses_small_task_tier(self):
        result = route_query("What is 2+2?", root=ROOT)

        self.assertEqual(result["route_kind"], "small_task")
        self.assertEqual(result["model_tier"], "small_local")
        self.assertEqual(result["escalation_level"], 1)

    def test_capital_does_not_match_api_substring(self):
        result = route_query("What is the capital of France?", root=ROOT)

        self.assertEqual(result["route_kind"], "small_task")
        self.assertEqual(result["model_tier"], "small_local")

    def test_cantonese_capital_question_does_not_trigger_coordinate_cards(self):
        result = route_query("請用廣東話一句回答：法國首都係邊度？", root=ROOT)

        self.assertEqual(result["route_kind"], "small_task")
        self.assertEqual(result["model_tier"], "small_local")

    def test_polite_wrapper_keeps_bounded_formatting_small(self):
        result = route_query(
            "Please answer this briefly and directly: Return this title in title case: system health report.",
            root=ROOT,
        )

        self.assertEqual(result["route_kind"], "small_task")
        self.assertEqual(result["model_tier"], "small_local")

    def test_translation_of_code_request_is_language_task(self):
        result = route_query("Translate 'Fix this Python bug' into French.", root=ROOT)

        self.assertEqual(result["route_kind"], "small_task")

    def test_translation_of_upgrade_request_is_language_task(self):
        result = route_query("Translate 'self-upgrade benchmark harness report' into French.", root=ROOT)

        self.assertEqual(result["route_kind"], "small_task")

    def test_rewrite_python_function_remains_code_task(self):
        result = route_query("Rewrite this Python function to handle timeout errors.", root=ROOT)

        self.assertEqual(result["route_kind"], "code_task")

    def test_core_abstract_concept_uses_protocol_path(self):
        result = route_query("咩係自由？", root=ROOT)

        self.assertEqual(result["route_kind"], "deep_reasoning")
        self.assertEqual(result["model_tier"], "strong_reasoning")
        self.assertTrue(result["skip_pre_gate"])
        self.assertEqual(result["recommended_pipeline_mode"], "protocol_compact")
        self.assertEqual(result["cost_metrics"]["estimated_model_calls"], 2)
        self.assertIn("abstract/protocol concept", result["reason"])
        self.assertIn(
            "coordinate.freedom.entropy",
            {hit.get("id") for hit in result["coordinate_hits"]},
        )

    def test_abstract_concepts_without_specific_card_still_use_protocol_path(self):
        result = route_query("咩係愛？", root=ROOT)

        self.assertEqual(result["route_kind"], "deep_reasoning")
        self.assertEqual(result["model_tier"], "strong_reasoning")
        self.assertTrue(result["skip_pre_gate"])
        self.assertIn("abstract/protocol concept", result["reason"])

    def test_lie_cost_uses_compact_protocol_path(self):
        result = route_query("LIE_COST係咩？點解係5.85？", root=ROOT)

        self.assertEqual(result["route_kind"], "deep_reasoning")
        self.assertEqual(result["recommended_pipeline_mode"], "protocol_compact")
        self.assertEqual(result["cost_metrics"]["estimated_model_calls"], 2)

    def test_kairos_concept_explanation_uses_deep_reasoning_not_memory(self):
        result = route_query("Explain Kairos as a concept.", root=ROOT)

        self.assertEqual(result["route_kind"], "deep_reasoning")
        self.assertNotEqual(result.get("short_circuit"), "kairos_memory_direct")

    def test_conversation_memory_test_is_not_kairos_memory(self):
        result = route_query(
            "上下文記憶測試：臨時代號「白塔」代表「低成本路由測試」。"
            "呢個只係本輪對話上下文，唔需要寫入長期記憶。",
            root=ROOT,
        )

        self.assertNotEqual(result["route_kind"], "deterministic_memory")
        self.assertNotEqual(result.get("short_circuit"), "kairos_memory_direct")

    def test_context_followup_skips_small_task_gate(self):
        result = route_query(
            "青石2846 代表咩？只根據本輪對話上一句回答。",
            root=ROOT,
            in_session_history=[
                {"input": "本輪對話暫時使用一個代號：青石2846 = 橙色書籤。"},
            ],
        )

        self.assertEqual(result["route_kind"], "deep_reasoning"