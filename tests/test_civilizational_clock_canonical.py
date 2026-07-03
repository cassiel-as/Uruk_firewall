"""
Unit tests for civilizational_clock.py canonical Eq1 / Eq2 (v8.30 restoration).

Verifies the two equations restored from canonical spec:
    Eq 1: gap(n) ≈ 397 × 0.279ⁿ between major tech leaps (CAU-012)
    Eq 2: delay ≈ 329 / ln(velocity) anti-formatting reaction lag

Plus regression checks that existing Eq 3 / 4 / 5 + fallbacks still behave
the same.
"""

from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.civilizational_clock import (  # noqa: E402
    CivilizationalClock,
    EQ1_BASE_GAP,
    EQ1_DECAY_RATIO,
    EQ1_LAST_LEAP_N,
    EQ1_LAST_LEAP_YEAR,
    EQ2_AI_ERA_REFERENCE_YEAR,
    EQ2_AI_ERA_VELOCITY_DEFAULT,
    EQ2_CALIBRATION_POINTS,
    EQ2_DELAY_B_MULTIPLIER,
    EQ2_DELAY_COEFF,
    EQ2_KAIROS_D_0,
    TECH_LEAP_TIMELINE,
)


class Eq1CanonicalTests(unittest.TestCase):
    """Eq 1 canonical: gap(n) ≈ 397 × 0.279ⁿ — CAU-012 calibration."""

    def setUp(self) -> None:
        self.clock = CivilizationalClock()

    def test_constants_match_canonical(self) -> None:
        self.assertEqual(EQ1_BASE_GAP, 397.0)
        self.assertEqual(EQ1_DECAY_RATIO, 0.279)

    def test_gap_n0_anchor_397(self) -> None:
        """n=0 anchor: print→telegraph baseline."""
        r = self.clock.eq1_tech_leap_gap(0)
        self.assertEqual(r.equation, "eq1_tech_leap_gap")
        self.assertAlmostEqual(r.value, 397.0, places=3)

    def test_gap_n1_telegraph_to_internet(self) -> None:
        """n=1: 397 × 0.279 = 110.76 yr (observed telegraph→internet ≈ 154 yr)."""
        r = self.clock.eq1_tech_leap_gap(1)
        self.assertAlmostEqual(r.value, 110.763, places=2)

    def test_gap_n2_internet_to_ai_matches_observed(self) -> None:
        """n=2 calibration check: predicted ≈ 30.9 yr, CAU-012 observed = 31 yr."""
        r = self.clock.eq1_tech_leap_gap(2)
        self.assertGreaterEqual(r.value, 30.0)
        self.assertLessEqual(r.value, 32.0)

    def test_gap_n3_predicts_about_8_6_years(self) -> None:
        """n=3 prediction: 397 × 0.279³ = 8.62 yr."""
        r = self.clock.eq1_tech_leap_gap(3)
        self.assertGreaterEqual(r.value, 8.0)
        self.assertLessEqual(r.value, 9.5)

    def test_predict_next_leap_year_lands_2031(self) -> None:
        """Canonical prediction: AI(2022) + gap(3) ≈ 2030.6 → rounds to 2031."""
        p = self.clock.eq1_predict_next_leap_year()
        self.assertEqual(p["predicted_year"], 2031)
        self.assertEqual(p["last_n"], EQ1_LAST_LEAP_N)
        self.assertEqual(p["last_leap_year"], EQ1_LAST_LEAP_YEAR)
        self.assertEqual(p["next_n"], 3)
        self.assertAlmostEqual(p["predicted_gap_yr"], 8.622, places=2)

    def test_predict_next_leap_year_custom_anchor(self) -> None:
        """Override anchor: explicit (year, n) tuple."""
        p = self.clock.eq1_predict_next_leap_year(last_leap_year=2000, last_n=1)
        # 2000 + 397 × 0.279^2 = 2000 + 30.9 = 2031
        self.assertEqual(p["predicted_year"], 2031)

    def test_timeline_includes_cau012_full_sequence(self) -> None:
        """CAU-012 sequence must be exposed for inspection."""
        names = [(t["from"], t["to"]) for t in TECH_LEAP_TIMELINE]
        self.assertIn(("print", "telegraph"), names)
        self.assertIn(("telegraph", "internet"), names)
        self.assertIn(("internet", "ai_emergence"), names)
        # And the pre-exponential regime is flagged
        pre_exp = [t for t in TECH_LEAP_TIMELINE if not t["fits_canonical"]]
        self.assertGreaterEqual(len(pre_exp), 2)  # fire/agriculture + agriculture/writing

    def test_negative_n_emits_caveat(self) -> None:
        r = self.clock.eq1_tech_leap_gap(-1)
        self.assertTrue(any("deep-prehistory" in c for c in r.caveats))


class Eq2CanonicalTests(unittest.TestCase):
    """Eq 2 canonical (v8.30 fidelity-aligned to paper §5.2):
    delay_A ≈ 268 / ln(velocity) × exp(-D/83.5)."""

    def setUp(self) -> None:
        self.clock = CivilizationalClock()

    def test_constants_match_canonical(self) -> None:
        """v8.30: 329 → 268 (canonical 4-point fit)."""
        self.assertEqual(EQ2_DELAY_COEFF, 268.0)
        self.assertEqual(EQ2_DELAY_B_MULTIPLIER, 4.5)
        self.assertEqual(EQ2_KAIROS_D_0, 83.5)

    def test_luther_print_calibration(self) -> None:
        """Luther/print: 268/ln(100) = 58.2 yr (observed 77)."""
        r = self.clock.eq2_anti_format_delay_canonical(velocity=100.0)
        self.assertAlmostEqual(r.value, 268.0 / math.log(100), places=2)
        # Within sensitivity range — paper notes calibration range 166-354
        self.assertGreater(r.value, 50.0)

    def test_snowden_calibration_close_to_22(self) -> None:
        """Snowden/internet: 268/ln(1e6) = 19.4 yr (observed 22)."""
        r = self.clock.eq2_anti_format_delay_canonical(velocity=1.0e6)
        self.assertAlmostEqual(r.value, 268.0 / math.log(1.0e6), places=2)
        # Within ±5 of observed 22
        self.assertGreaterEqual(r.value, 14.0)
        self.assertLessEqual(r.value, 25.0)

    def test_invalid_velocity_returns_nan(self) -> None:
        r = self.clock.eq2_anti_format_delay_canonical(velocity=1.0)
        self.assertTrue(math.isnan(r.value))

    def test_window_close_year_lands_2035(self) -> None:
        """Canonical paper: AI velocity 1e9 + reference 2022 → 2022+13 ≈ 2035."""
        w = self.clock.eq2_window_close_year()
        self.assertEqual(w["close_year"], 2035)
        self.assertEqual(w["reference_year"], EQ2_AI_ERA_REFERENCE_YEAR)
        self.assertEqual(w["velocity"], EQ2_AI_ERA_VELOCITY_DEFAULT)
        self.assertEqual(w["mode"], "A")
        self.assertGreaterEqual(w["predicted_delay_yr"], 12.0)
        self.assertLessEqual(w["predicted_delay_yr"], 14.0)

    def test_window_close_year_mode_B_institutional_2080(self) -> None:
        """delay_B = delay_A × 4.5 → 2022 + 58.5 ≈ 2080."""
        w = self.clock.eq2_window_close_year(mode="B")
        # 268/ln(1e9) × 4.5 ≈ 58.5 yr → 2022 + 58.5 ≈ 2081 (rounded)
        self.assertGreaterEqual(w["close_year"], 2078)
        self.assertLessEqual(w["close_year"], 2082)
        self.assertEqual(w["mode"], "B")

    def test_kairos_density_2019_anchor_matches_paper(self) -> None:
        """Paper §6.3: π=8.5, |ε|=9.0, r=1.0 → D=76.5."""
        d = self.clock.eq2_kairos_density(precision=8.5,
                                          error_magnitude=9.0,
                                          irreversibility=1.0)
        self.assertAlmostEqual(d["D_event"], 76.5, places=1)

    def test_kairos_correction_reduces_delay(self) -> None:
        """High Kairos D → shorter delay (exp(-D/83.5) < 1)."""
        no_anchor = self.clock.eq2_anti_format_delay_canonical(1.0e9, kairos_density=0.0)
        anchored = self.clock.eq2_anti_format_delay_canonical(1.0e9, kairos_density=76.5)
        # Paper: D=76.5 → f≈0.40 → delay halves roughly
        self.assertLess(anchored.value, no_anchor.value)
        self.assertAlmostEqual(anchored.value / no_anchor.value,
                               math.exp(-76.5 / 83.5),
                               places=4)

    def test_kairos_irreversibility_clamped(self) -> None:
        """r ∈ [0, 1] enforced."""
        d_high = self.clock.eq2_kairos_density(1.0, 1.0, irreversibility=999.0)
        self.assertEqual(d_high["irreversibility"], 1.0)
        d_neg = self.clock.eq2_kairos_density(1.0, 1.0, irreversibility=-5.0)
        self.assertEqual(d_neg["irreversibility"], 0.0)

    def test_calibration_points_4_point_canonical(self) -> None:
        """v8.30: now 4 calibration points (was 2)."""
        eras = [pt["era"] for pt in EQ2_CALIBRATION_POINTS]
        self.assertIn("luther_print", eras)
        self.assertIn("telegraph", eras)
        self.assertIn("radio", eras)
        self.assertIn("snowden_internet", eras)
        self.assertEqual(len(EQ2_CALIBRATION_POINTS), 4)


class FallbackAndRegressionTests(unittest.TestCase):
    """Eq 3 / 4 / 5 + Eq1/Eq2 fallbacks must still behave unchanged."""

    def setUp(self) -> None:
        self.clock = CivilizationalClock()

    def test_eq1_fallback_alias_unchanged(self) -> None:
        """eq1_tech_leap (back-compat alias) still uses 2.5 ratio."""
        r = self.clock.eq1_tech_leap(1.0, 2.0)
        self.assertEqual(r.value, 6.25)  # 1.0 × 2.5^2

    def test_eq1_fallback_explicit(self) -> None:
        r = self.clock.eq1_tech_leap_rate(1.0, 2.0)
        self.assertEqual(r.value, 6.25)
        self.assertTrue(any("canonical is eq1_tech_leap_gap" in c for c in r.caveats))

    def test_eq2_fallback_band_unchanged(self) -> None:
        d = self.clock.eq2_anti_format_delay()
        self.assertEqual(d["band_years"], [12, 30])
        self.assertEqual(d["midpoint"], 20)
        self.assertIn("calibrated_references", d)

    def test_eq2_fallback_inside_band_check(self) -> None:
        d = self.clock.eq2_anti_format_delay(observed_years=20)
        self.assertTrue(d["inside_band"])
        d2 = self.clock.eq2_anti_format_delay(observed_years=50)
        self.assertFalse(d2["inside_band"])

    def test_eq3_unchanged(self) -> None:
        r = self.clock.eq3_format_scale(1.0, 2.0)
        self.assertEqual(r.value, 6.25)  # 1.0 × 2.5^2

    def test_eq4_unchanged(self) -> None:
        d = self.clock.eq4_cost_transfer(70)
        # 309.7 × 70^(-0.631) = 21.217
        self.assertAlmostEqual(d["wealth_transfer_W"], 21.217, places=2)

    def test_eq5a_external_unchanged(self) -> None:
        d = self.clock.eq5_collapse_threshold(50, mode="external", acute_shock=1.0)
        self.assertAlmostEqual(d["threshold_ratio"], 50 / 167, places=3)
        self.assertTrue(d["collapse_imminent"])  # 50/167 + 1.0 = 1.30 >= 1.0

    def test_eq5b_internal_unchanged(self) -> None:
        d = self.clock.eq5_collapse_threshold(12, mode="internal", acute_shock=1.0)
        self.assertAlmostEqual(d["threshold_ratio"], 12 / 41, places=3)


class SnapshotSurfacesCanonicalPredictionsTests(unittest.TestCase):
    """snapshot() must surface the two canonical predictions for dispatcher."""

    def setUp(self) -> None:
        self.clock = CivilizationalClock()

    def test_snapshot_triggers_on_tech_leap_query(self) -> None:
        s = self.clock.snapshot("Next tech leap prediction please")
        self.assertTrue(s["active"])
        self.assertIn("predictions", s)
        # v8.30 canonical: next leap 2031, AI-era window close 2035
        self.assertEqual(s["predictions"]["next_tech_leap_year"]["predicted_year"], 2031)
        self.assertEqual(s["predictions"]["anti_format_window_close"]["close_year"], 2035)

    def test_snapshot_exposes_canonical_constants(self) -> None:
        s = self.clock.snapshot("civilizational clock review")
        c = s["constants"]
        self.assertEqual(c["eq1_base_gap"], 397.0)
        self.assertEqual(c["eq1_decay_ratio"], 0.279)
        # v8.30: 329 → 268
        self.assertEqual(c["eq2_delay_coeff"], 268.0)
        # Fallback constants also still there
        self.assertEqual(c["tech_ratio"], 2.5)

    def test_snapshot_quiet_on_unrelated_query(self) -> None:
        s = self.clock.snapshot("how do I make tea")
        self.assertFalse(s["active"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
