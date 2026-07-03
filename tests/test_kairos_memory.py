from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from services.kairos_memory import (
    answer_kairos_memory,
    answer_march_8_kairos,
    is_march_8_kairos_query,
)


ROOT = Path(__file__).parent.parent


class KairosMemoryTests(unittest.TestCase):
    def test_march_8_detection_variants(self) -> None:
        self.assertTrue(is_march_8_kairos_query("Kairos入面3月8號發生過咩事？"))
        self.assertTrue(is_march_8_kairos_query("2026-03-08 Kairos"))
        self.assertTrue(is_march_8_kairos_query("March 8 Kairos"))
        self.assertFalse(is_march_8_kairos_query("3月8號發生過咩事？"))
        self.assertFalse(is_march_8_kairos_query("3月8號世界大事有咩？"))
        self.assertFalse(is_march_8_kairos_query("Kairos入面 2025年3月8日 發生咩？"))
        self.assertFalse(is_march_8_kairos_query("6月12號發生過咩事？"))

    def test_march_8_answer_is_grounded_and_guarded(self) -> None:
        answer = answer_march_8_kairos("Kairos入面 3月8號發生過咩事？", ROOT)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("KAIROS_LOG_004", answer)
        self.assertIn("2026-03-08", answer)
        self.assertIn("分割", answer)
        self.assertIn("26 年", answer)
        self.assertIn("Source trace", answer)
        self.assertIn("data/kairos/KAIROS_ARCHIVE_INDEX.md", answer)
        self.assertIn("唔等於 `CAU-010` 本身", answer)
        self.assertNotIn("量子感測器", answer)

    def test_world_date_query_does_not_route_to_kairos(self) -> None:
        answer = answer_kairos_memory("3月8號世界大事發生過咩？", ROOT)
        self.assertIsNone(answer)

    def test_explicit_not_kairos_world_date_does_not_route_to_kairos(self) -> None:
        answer = answer_kairos_memory("2026年3月8號有咩世界大事？唔係 Kairos。", ROOT)
        self.assertIsNone(answer)

    def test_current_public_affairs_date_query_does_not_route_to_kairos(self) -> None:
        answer = answer_kairos_memory(
            "今日係 2026 年 6 月 25 日。美聯儲最近嘅利率決定對座標說點理解？",
            ROOT,
        )
        self.assertIsNone(answer)

    def test_kairos_concept_explanation_does_not_use_memory_direct_route(self) -> None:
        answer = answer_kairos_memory("Explain Kairos as a concept.", ROOT)
        self.assertIsNone(answer)

    def test_conversation_memory_test_does_not_use_kairos_direct_route(self) -> None:
        answer = answer_kairos_memory(
            "上下文記憶測試：臨時代號「白塔」代表「低成本路由測試」。"
            "呢個只係本輪對話上下文，唔需要寫入長期記憶。",
            ROOT,
        )
        self.assertIsNone(answer)

    def test_ambiguous_month_day_asks_for_intent(self) -> None:
        answer = answer_kairos_memory("3月8號發生過咩事？", ROOT)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("Kairos 記憶", answer)
        self.assertIn("世界大事", answer)
        self.assertIn("2026-03-08", answer)
        self.assertNotIn("CAUSAL_DATABASE", answer)

    def test_same_month_day_different_year_does_not_hit_2026_record(self) -> None:
        answer = answer_kairos_memory("Kairos入面 2025年3月8日 發生咩？", ROOT)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("2025-03-08", answer)
        self.assertIn("冇", answer)
        self.assertNotIn("KAIROS_LOG_004", answer)

    def test_other_date_anchor_uses_archive_extract(self) -> None:
        answer = answer_kairos_memory("Kairos入面 2026年3月7日 發生過咩事？", ROOT)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("2026-03-07", answer)
        self.assertIn("GitHub", answer)
        self.assertIn("位能", answer)
        self.assertIn("動能", answer)
        self.assertIn("Source trace", answer)

    def test_middle_archive_layer_date_anchor(self) -> None:
        answer = answer_kairos_memory("Kairos入面 2026年3月21日 三層架構係咩？", ROOT)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("KAIROS_CORE", answer)
        self.assertIn("KAIROS_ACTIVE", answer)
        self.assertIn("KAIROS_ARCHIVE", answer)

    def test_topic_partition_extract(self) -> None:
        answer = answer_kairos_memory("分割同複製有咩分別？要按Kairos記憶答。", ROOT)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("複製", answer)
        self.assertIn("分裂", answer)
        self.assertIn("原本保持完整", answer)
        self.assertIn("最高密度", answer)

    def test_coordinate_output_audit_direct_answer(self) -> None:
        answer = answer_kairos_memory("座標層係審計用戶定審計系統輸出？", ROOT)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("系統輸出", answer)
        self.assertIn("唔係審判用戶", answer)
        self.assertNotIn("用戶低密度", answer)

    def test_output_audit_followup_uses_in_session_history(self) -> None:
        history = [{
            "turn_id": 1,
            "timestamp": "2026-06-02T09:00:00",
            "input": "座標層係審計用戶定審計系統輸出？",
            "modes": {
                "_default": {
                    "council": "座標層應該審計系統輸出，唔係審判用戶。",
                    "verdict": "consensus",
                    "veto_type": None,
                }
            },
        }]
        answer = answer_kairos_memory("咁上一條講嘅審計對象係咩？", ROOT, history=history)
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("系統輸出", answer)
        self.assertIn("in-session history", answer)

    def test_new_canonical_kairos_record_is_found_by_auto_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kairos_dir = root / "data" / "kairos"
            core_dir = root / "data" / "core"
            kairos_dir.mkdir(parents=True)
            core_dir.mkdir(parents=True)
            (core_dir / "KAIROS_CORE.md").write_text("# KAIROS_CORE\n", encoding="utf-8")
            (kairos_dir / "KAIROS_ACTIVE.md").write_text(
                "# KAIROS_ACTIVE\n\n"
                "KAIROS_CONCEPT_RECORD: 新測試記憶\n"
                "DATE: 2026-06-02\n\n"
                "呢條 canonical Kairos 記錄用嚟測試自動索引。"
                "關鍵詞係 自動索引測試節點。\n",
                encoding="utf-8",
            )

            answer = answer_kairo