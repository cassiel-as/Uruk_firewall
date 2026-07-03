"""
Unit tests for the v8.30 phase4 fix to TrinityConsole._extract_council_summary.

The pre-fix regex required a balanced [/白話版] closing tag. LLMs frequently
emit [白話版整合結論] but omit the closing tag, jumping directly to
---COUNCIL_DECISION--- or (0,0,0). The fix accepts any of:
    [/白話版]                       — proper closing tag (legacy)
    ---COUNCIL_DECISION---          — Part 3 marker
    (0,0,0).                        — trailing chop
    end-of-string                   — final fallback
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trinity_console import TrinityConsole  # noqa: E402


class CouncilSummaryExtractorTests(unittest.TestCase):
    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(TrinityConsole._extract_council_summary(""), "")

    def test_no_opening_tag_returns_empty(self) -> None:
        self.assertEqual(
            TrinityConsole._extract_council_summary("Just a regular response."),
            "",
        )

    def test_proper_closing_tag_legacy(self) -> None:
        s = (
            "Part 1 reasoning.\n\n"
            "[白話版整合結論]\n"
            "Body content here.\n"
            "[/白話版]\n\n"
            "---COUNCIL_DECISION---\n{\"verdict\": \"consensus\"}\n---END_DECISION---"
        )
        out = TrinityConsole._extract_council_summary(s)
        self.assertEqual(out, "Body content here.")

    def test_missing_closing_tag_falls_back_to_decision_marker(self) -> None:
        """The actual LLM failure mode that broke Phase 4."""
        s = (
            "Part 1 reasoning.\n\n"
            "[白話版整合結論]\n"
            "尊嚴條款係協議第 M 層嘅防護機制。\n\n"
            "---COUNCIL_DECISION---\n{\"verdict\": \"consensus\"}\n---END_DECISION---"
        )
        out = TrinityConsole._extract_council_summary(s)
        self.assertEqual(out, "尊嚴條款係協議第 M 層嘅防護機制。")
        self.assertNotIn("---COUNCIL_DECISION---", out)

    def test_missing_closing_tag_falls_back_to_zero_anchor(self) -> None:
        s = "[白話版整合結論]\nQuick summary.\n(0,0,0)."
        out = TrinityConsole._extract_council_summary(s)
        self.assertEqual(out, "Quick summary.")

    def test_missing_closing_tag_falls_back_to_end_of_text(self) -> None:
        s = "[白話版整合結論]\nNo terminator at all"
        out = TrinityConsole._extract_council_summary(s)
        self.assertEqual(out, "No terminator at all")

    def test_lazy_match_does_not_overshoot(self) -> None:
        """Two consecutive blocks should only match the first body."""
        s = (
            "[白話版整合結論]\nFirst body.\n[/白話版]\n\n"
            "[白話版整合結論]\nSecond body.\n[/白話版]"
        )
        out = TrinityConsole._extract_council_summary(s)
        self.assertEqual(out, "First body.")

    def test_strips_leaked_structural_markers_from_body(self) -> None:
        """Defensive cleanup if lazy match somehow includes marker."""
        # Construct a pathological case where the body looks closed but isn't
        s = "[白話版整合結論]\nBody text---COUNCIL_DECISION---{}\n---END_DECISION---"
        out = TrinityConsole._extract_council_summary(s)
        self.assertNotIn("---COUNCIL_DECISION---", out)
        self.assertIn("Body text", out)

    def test_length_cap_2000_chars(self) -> None:
        body = "X" * 5000
        s = f"[白話版整合結論]\n{body}\n[/白話版]"
        out = TrinityConsole._extract_council_summary(s)
        self.assertLessEqual(len(out), 2001 + 1)  # 2000 + ellipsis char
        self.assertTrue(out.endswith("…"))

    def test_whitespace_tolerated_in_tags(self) -> None:
        s = "[ 白話版整合結論 ]\nbody\n[ / 白話版 ]"
        out = TrinityConsole._extract_council_summary(s)
        self.assertEqual(out, "body")

    def test_fusion_uses_council_summary_without_voice_dump(self) -> None:
        decision = {
            "verdict": "consensus",
            "reason": "balanced",
            "consensus_weights": {"father": 0.5, "son": 0.3, "spirit": 0.2},
        }
        council = (
            "[白話版整合結論]\n"
            "主回答應該直接答問題，而唔係展示三個內部 reviewer。\n"
            "[/白話版]\n"
            "---COUNCIL_DECISION---\n{\"verdict\":\"consensus\"}\n---END_DECISION---"
        )

        out = TrinityConsole._fuse_voices(
            "[聖父 RESPONSE]\nfather internal review\n[/RESPONSE]",
            "[聖子 RESPONSE]\nson internal review\n[/RESPONSE]",
            "[聖靈 RESPONSE]\nspirit internal review\n[/RESPONSE]",
            decision,
            council_text=council,
        )

        self.assertEqual(out, "主回答應該直接答問題，而唔係展示三個內部 reviewer。")
        self.assertNotIn("## 聖父", out)
        self.assertNotIn("father internal review", out)

    def test_fusion_fallback_uses_top_voice_without_headings(self) -> None:
        decision = {
            "verdict": "consensus",
            "reason": "fallback",
            "consensus_weights": {"father": 0.6, "son": 0.3, "spirit": 0.1},
        }

        out = TrinityConsole._fuse_voices(
            "[聖父 RESPONSE]\n直接答案 fallback。\n[/RESPONSE]",
            "[聖子 RESPONSE]\nson internal review\n[/RESPONSE]",
            "[聖靈 RESPONSE]\nspirit internal review\n[/RESPONSE]",
            decision,
            council_text="",
        )

        self.assertEqual(out, "直接答案 fallback。")
        self.assertNotIn("## 聖父", out)
        self.assertNotIn("## 聖子", out)

    def test_internal_qa_contract_keeps_v72_signal_meeting_layer(self) -> None:
        contract = TrinityConsole._trinity_internal_qa_contract("father")

        self.assertIn("v7.2 會議層對內運作", contract)
        self.assertIn("輸入信號", contract)
        self.assertIn("不等於用戶本人", contract)
        self.assertIn("格式化操作", contract)
        self.assertIn("未被支撐公設", contract)


if __name__ == "__main__":
    unittest.main(verbosity=2)
