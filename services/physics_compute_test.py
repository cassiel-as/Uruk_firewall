"""Unit tests for physics_compute — v8.37.

Verify COMPUTED values match known mathematical expectations on canonical
inputs, so we cannot drift into "looks plausible" territory.
"""

import math
import unittest

from services.physics_compute import (
    LIE_COST_CALIBRATION,
    FREEDOM_LOSS_ENTROPY_CALIBRATION,
    LANDAUER_FLOOR_J_PER_BIT,
    _shannon_entropy_bits_per_char,
    _gzip_compression_ratio,
    _js_divergence_chars,
    compute_per_query,
    to_event_payload,
)


class TestShannonEntropy(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_shannon_entropy_bits_per_char(""), 0.0)

    def test_single_char(self):
        # All same char → H = 0 (no uncertainty)
        self.assertAlmostEqual(_shannon_entropy_bits_per_char("aaaaaaa"), 0.0, places=6)

    def test_two_equal_chars(self):
        # 50/50 distribution → H = 1 bit/char exactly
        self.assertAlmostEqual(_shannon_entropy_bits_per_char("ab"), 1.0, places=6)
        self.assertAlmostEqual(_shannon_entropy_bits_per_char("abab"), 1.0, places=6)

    def test_four_equal_chars(self):
        # 4 chars each 1/4 → H = log₂ 4 = 2 bits/char
        self.assertAlmostEqual(_shannon_entropy_bits_per_char("abcd"), 2.0, places=6)
        self.assertAlmostEqual(_shannon_entropy_bits_per_char("abcdabcd"), 2.0, places=6)

    def test_bounded_by_log_alphabet(self):
        # For ASCII letters only, H ≤ log₂ 26 ≈ 4.7
        s = "abcdefghijklmnopqrstuvwxyz"
        h = _shannon_entropy_bits_per_char(s)
        self.assertLessEqual(h, math.log2(26) + 1e-9)
        self.assertAlmostEqual(h, math.log2(26), places=6)


class TestGzipRatio(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_gzip_compression_ratio(""), 0.0)

    def test_highly_redundant_lower_than_random(self):
        # Repeated string compresses much smaller than mixed random
        redundant = "a" * 1000
        mixed = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 18
        r_red = _gzip_compression_ratio(redundant)
        r_mix = _gzip_compression_ratio(mixed)
        self.assertLess(r_red, r_mix)
        # Sanity bounds: both > 0
        self.assertGreater(r_red, 0.0)
        self.assertGreater(r_mix, 0.0)


class TestJSDivergence(unittest.TestCase):
    def test_identical_strings(self):
        # JSD(P||P) = 0
        self.assertAlmostEqual(_js_divergence_chars("hello world", "hello world"), 0.0, places=6)

    def test_empty_one_side(self):
        self.assertEqual(_js_divergence_chars("", "anything"), 0.0)
        self.assertEqual(_js_divergence_chars("anything", ""), 0.0)

    def test_disjoint_alphabets_approaches_ln2(self):
        # Disjoint char sets → JSD ≈ ln 2
        js = _js_divergence_chars("aaaa", "bbbb")
        self.assertAlmostEqual(js, math.log(2), places=6)

    def test_bounded_by_ln2(self):
        # Always in [0, ln 2]
        js = _js_divergence_chars("the quick brown fox", "xyz")
        self.assertGreaterEqual(js, 0.0)
        self.assertLessEqual(js, math.log(2) + 1e-9)


class TestPhysicalLaw(unittest.TestCase):
    def test_landauer_floor_is_real(self):
        # k_B · T · ln 2 @ 300 K ≈ 2.87e-21 J/bit
        expected = 1.380649e-23 * 300.0 * math.log(2)
        self.assertAlmostEqual(LANDAUER_FLOOR_J_PER_BIT, expected, places=27)
        # Sanity: ~2.87e-21
        self.assertLess(LANDAUER_FLOOR_J_PER_BIT, 1e-20)
        self.assertGreater(LANDAUER_FLOOR_J_PER_BIT, 1e-22)


class TestCalibrationAnchors(unittest.TestCase):
    def test_values_match_protocol_doc(self):
        # These MUST stay aligned with PHYSICS_CONSTANTS.md.
        self.assertEqual(LIE_COST_CALIBRATION, 5.85)
        self.assertEqual(FREEDOM_LOSS_ENTROPY_CALIBRATION, 8.19)


class TestComputePerQuery(unittest.TestCase):
    def test_returns_8_metrics(self):
        metrics = compute_per_query("hello", "world output")
        self.assertEqual(len(metrics), 8)

    def test_all_metrics_have_required_keys(self):
        metrics = compute_per_query("hi", "there")
        required = {"name", "value", "unit", "label", "method", "caveat"}
        for m in metrics:
            self.assertEqual(set(m.keys()), required)

    def test_labels_are_canonical(self):
        metrics = compute_per_query("a", "b")
        allowed = {"COMPUTED", "CALIBRATION", "PHYSICAL_LAW", "ANALOGY"}
        labels = {m["label"] for m in metrics}
        self.assertTrue(labels.issubset(allowed))

    def test_analogy_metrics_carry_caveat(self):
        metrics = compute_per_query("a", "b")
        for m in metrics:
            if m["label"] == "ANALOGY":
                self.assertIsNotNone(m["caveat"])
                self.assertGreater(len(m["caveat"]), 50)

    def test_computed_metrics_no_caveat(self):
        metrics = compute_per_query("a", "b")
        for m in metrics:
            if m["label"] == "COMPUTED":
                self.assertIsNone(m["caveat"])

    def test_handles_empty_inputs(self):
        # Must not crash on empty / None inputs
        metrics = compute_per_query("", "")
        self.assertEqual(len(metrics), 8)
        metrics = compute_per_query(None, None)
        self.assertEqual(len(metrics), 8)


class TestEventPayload(unittest.TestCase):
    def test_payload_shape(self):
        p = to_event_payload("hi", "there")
        self.assertIn("display_label", p)
        self.assertIn("metrics", p)
        self.assertIn("物理計算", p["display_label"])
        self.assertIn("dev-only", p["display_label"])
        self.assertIn("唔影響", p["display_label"])


if __name__ == "__main__":
    unittest.main()
