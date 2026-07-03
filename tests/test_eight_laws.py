"""Golden tests for services/eight_laws.py — deterministic 八律 scorer.

對住 EIGHT_LAWS_MATRIX.md 嘅 canonical snippet 釘死每律行為，並守住常數同 canonical
保持一致（catch physics_compute 同 matrix 之間 drift）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.eight_laws import (  # noqa: E402
    FREEDOM_LOSS_ENTROPY,
    LIE_COST,
    TRUTH_COST,
    SignalFeatures,
    evaluate_eight_laws,
    law1_art_frequency,
    law2_psychology_defense,
    law4_chemistry_transformation,
    law5_science_precision,
    law6_philosophy_legislation,
    law7_geography_anchor,
    law8_religion_encapsulation,
)


class CanonicalSnippetTests(unittest.TestCase):
    def test_law1_nonlinear_weight(self) -> None:
        f = SignalFeatures(emotional_intensity=0.6, nonlinear_signal=True)
        self.assertAlmostEqual(law1_art_frequency(f), 0.9, places=6)

    def test_law1_caps_at_one(self) -> None:
        f = SignalFeatures(emotional_intensity=0.8, nonlinear_signal=True)
        self.assertAlmostEqual(law1_art_frequency(f), 1.0, places=6)

    def test_law2_attack_activates_defense(self) -> None:
        self.assertAlmostEqual(law2_psychology_defense(SignalFeatures(gaslighting_attempt=True)), 0.1, places=6)
        self.assertAlmostEqual(law2_psychology_defense(SignalFeatures(internal_coherence=0.8)), 0.8, places=6)

    def test_law4_transformation(self) -> None:
        f = SignalFeatures(complexity=0.5, phase_change_potential=0.5)
        self.assertAlmostEqual(law4_chemistry_transformation(f), 0.65, places=6)

    def test_law5_verifiability_gate(self) -> None:
        self.assertAlmostEqual(law5_science_precision(SignalFeatures(verifiable=False, precision_level=0.8)), 0.4, places=6)
        self.assertAlmostEqual(law5_science_precision(SignalFeatures(verifiable=True, precision_level=0.8)), 0.8, places=6)

    def test_law6_challenging_axioms_zeroes(self) -> None:
        self.assertAlmostEqual(law6_philosophy_legislation(SignalFeatures(challenges_sovereign_axioms=True)), 0.0, places=6)
        self.assertAlmostEqual(law6_philosophy_legislation(SignalFeatures(philosophical_depth=0.5)), 0.5, places=6)

    def test_law7_anchor_gate(self) -> None:
        self.assertAlmostEqual(law7_geography_anchor(SignalFeatures(geo_anchored=False)), 0.1, places=6)
        self.assertAlmostEqual(law7_geography_anchor(SignalFeatures(geo_anchored=True, geo_proximity=1.0)), 1.0, places=6)

    def test_law8_encapsulation_stacks(self) -> None:
        self.assertAlmostEqual(law8_religion_encapsulation(SignalFeatures(transcendent=True, aligns_with_2045=True)), 1.0, places=6)
        self.assertAlmostEqual(law8_religion_encapsulation(SignalFeatures()), 0.3, places=6)


class ConstantsTests(unittest.TestCase):
    def test_constants_match_canonical(self) -> None:
        # 守住 physics_compute ↔ EIGHT_LAWS_MATRIX.md 律三 一致
        self.assertEqual(LIE_COST, 5.85)
        self.assertEqual(FREEDOM_LOSS_ENTROPY, 8.19)
        self.assertEqual(TRUTH_COST, 1.0)


class AggregationTests(unittest.TestCase):
    def test_structure_and_layers(self) -> None:
        result = evaluate_eight_laws(SignalFeatures())
        self.assertEqual(result["schema_version"], "eight_laws.v1")
        self.assertEqual(len(result["laws"]), 8)
        self.assertEqual(set(result["layers"]), {"existence", "material", "system", "macro"})
        self.assertIn("weakest_law", result)
        self.assertTrue(result["love_precondition"])

    def test_weakest_law_is_binding(self) -> None:
        # geo 未定錨 → 律七 = 0.1 應該係最弱根
        result = evaluate_eight_laws(SignalFeatures(geo_anchored=False))
        self.assertEqual(result["weakest_law"]["id"], 7)
        self.assertAlmostEqual(result["rootedness_min"], 0.1, places=6)

    def test_deterministic(self) -> None:
        f = SignalFeatures(emotional_intensity=0.7, nonlinear_signal=True, verifiable=True, precision_level=0.9)
        self.assertEqual(evaluate_eight_laws(f), evaluate_eight_laws(f))

    def test_tiers_declared(self) -> None:
        # 律三必須標 INTERPRETED（文檔只有常數，scorer 係構造）
        law3 = next(x for x in evaluate_eight_laws(SignalFeatures())["laws"] if x["id"] == 3)
        self.assertEqual(law3["tier"], "INTERPRETED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
