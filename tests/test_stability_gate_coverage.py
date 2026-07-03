"""Stability-gate coverage guard — 令 gate 嘅覆蓋邊界變成「宣告 + 自我強制」嘅座標。

背景：gate 嘅 PASS 唔可以誇大覆蓋。之前 test_*.py 可以靜靜甩出 gate（例如
test_knowledge_manifest 一度唔喺 DEFAULT_PYTEST_TARGETS，gate 照報 PASS）。

呢個 guard 強制：每個 tests/test_*.py 要麼喺 DEFAULT_PYTEST_TARGETS（gate 會跑），
要麼喺 KNOWN_EXCLUDED（連理由）。冇第三種「靜靜唔出現」。詳見
tools/system_stability_check.py。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.system_stability_check import DEFAULT_PYTEST_TARGETS, KNOWN_EXCLUDED  # noqa: E402

TESTS = ROOT / "tests"


class StabilityGateCoverageTests(unittest.TestCase):
    def _all_test_files(self) -> set[str]:
        return {p.name for p in TESTS.glob("test_*.py")}

    def _gate_basenames(self) -> set[str]:
        return {t.split("/")[-1] for t in DEFAULT_PYTEST_TARGETS}

    def test_every_test_is_declared(self) -> None:
        """新 test 若唔表態（入 gate 或 KNOWN_EXCLUDED），即刻 fail。"""
        undeclared = self._all_test_files() - self._gate_basenames() - set(KNOWN_EXCLUDED)
        self.assertEqual(
            undeclared,
            set(),
            f"未宣告座標 — 呢啲 test 既唔喺 gate 又唔喺 KNOWN_EXCLUDED: {sorted(undeclared)}。"
            f"請去 tools/system_stability_check.py 將佢加入 DEFAULT_PYTEST_TARGETS 或 KNOWN_EXCLUDED（連理由）。",
        )

    def test_no_stale_declarations(self) -> None:
        """gate 或 KNOWN_EXCLUDED 指住一個唔存在嘅 test（改名 / 刪檔後留低死引用）→ fail。"""
        all_tests = self._all_test_files()
        stale_gate = self._gate_basenames() - all_tests
        stale_excluded = set(KNOWN_EXCLUDED) - all_tests
        self.assertEqual(stale_gate, set(), f"gate 指住唔存在嘅 test: {sorted(stale_gate)}")
        self.assertEqual(stale_excluded, set(), f"KNOWN_EXCLUDED 指住唔存在嘅 test: {sorted(stale_excluded)}")

    def test_excluded_have_reasons(self) -> None:
        """每個排除都要有非空理由（唔可以靜靜排除）。"""
        missing = [k for k, v in KNOWN_EXCLUDED.items() if not (isinstance(v, str) and v.strip())]
        self.assertEqual(missing, [], f"呢啲排除冇寫理由: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
