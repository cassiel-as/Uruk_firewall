"""
Per-query physics computation — v8.37

Computes information-theoretic quantities from actual input/output text on each
query, alongside calibration anchors taken from PHYSICS_CONSTANTS.md. The point
of this module is **honesty about what is real vs analogy**:

  * COMPUTED      — actual math on this query's bytes. Reproducible, verifiable.
  * CALIBRATION   — fixed-value anchors from the protocol document.
  * PHYSICAL_LAW  — established physics constants (e.g. Landauer floor).
  * ANALOGY       — calibration values that depend on an UNPROVEN extrapolation
                    (specifically Landauer-to-cognition). Every consumer must
                    see the caveat.

This module exists so users can see a *real* per-query computed number alongside
the fixed 5.85 / 8.19, and judge for themselves where the boundary is.

CRITICAL: nothing computed here goes into the eight-law scoring, the council
fusion, or any prompt body. It surfaces as a dev-mode SSE event only.
"""

from __future__ import annotations

import gzip
import math
from collections import Counter
from typing import Dict, List


# ──────────────────────────────────────────────────────────────────────
# Constants — from PHYSICS_CONSTANTS.md (honest labels)
# ──────────────────────────────────────────────────────────────────────

#: Landauer floor: minimum thermodynamic cost to erase one bit at T=300K.
#: REAL physical law, validated experimentally on physical substrates.
#: Applying this to cognitive states is the ANALOGY (see below).
BOLTZMANN_J_PER_K = 1.380649e-23
ROOM_TEMP_K = 300.0
LANDAUER_FLOOR_J_PER_BIT = BOLTZMANN_J_PER_K * ROOM_TEMP_K * math.log(2)

#: Calibration anchors from PHYSICS_CONSTANTS.md §1.3 and §1.1.
#: Protocol document itself labels these as 「計算嘗試」 (computational
#: attempts), NOT validated measurements. They depend on extrapolating
#: Landauer's bit-erasure floor to macro-scale cognitive resistance, which
#: is an unproven analogy. Carried here for comparison ONLY.
LIE_COST_CALIBRATION = 5.85
FREEDOM_LOSS_ENTROPY_CALIBRATION = 8.19

#: The analogy caveat — attached to every ANALOGY-labelled metric so the
#: warning cannot be silently stripped downstream.
ANALOGY_CAVEAT = (
    "Landauer's principle (1961) is validated for physical bit-erasure on "
    "thermodynamic substrates only. Applying it to 'cognitive lie maintenance' "
    "or 'freedom-loss entropy' requires extrapolating from quantum-scale "
    "energy bounds to macro-scale cognitive resistance — an UNPROVEN analogy. "
    "PHYSICS_CONSTANTS.md itself labels these values as 計算嘗試 (computational "
    "attempts), not measurements. Use as protocol-internal comparison anchor; "
    "do NOT cite as physical fact."
)


# ──────────────────────────────────────────────────────────────────────
# Computation helpers — pure, deterministic, stdlib only
# ──────────────────────────────────────────────────────────────────────

def _shannon_entropy_bits_per_char(text: str) -> float:
    """Shannon entropy in bits per character over the actual char distribution.

    H(X) = -Σ p(x) · log₂(p(x))

    Real Shannon entropy. Bounded by log₂(|distinct chars|). For empty or
    single-char strings, returns 0.0 exactly.
    """
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    h = 0.0
    for c in counts.values():
        p = c / total
        if p > 0.0:
            h -= p * math.log2(p)
    return h


def _gzip_compression_ratio(text: str) -> float:
    """Kolmogorov-complexity upper bound proxy via gzip.

    Returns len(gzip(utf8(text))) / len(utf8(text)). Bounded in (0, ~1+].
    A truly random string approaches 1.0; a highly redundant string is well
    below 1.0. Not Kolmogorov complexity itself (which is uncomputable in
    general), but a reproducible computable upper bound.
    """
    if not text:
        return 0.0
    raw = text.encode("utf-8")
    if not raw:
        return 0.0
    compressed = gzip.compress(raw, compresslevel=6, mtime=0)
    return len(compressed) / len(raw)


def _js_divergence_chars(text_a: str, text_b: str) -> float:
    """Jensen-Shannon divergence between char distributions of two strings.

    JSD(P||Q) = ½·KL(P||M) + ½·KL(Q||M), where M = (P+Q)/2.

    Returns value in nats, bounded [0, ln 2]. Symmetric, always defined.
    Real information-theoretic quantity. 0 = identical distributions,
    ln 2 ≈ 0.693 = maximally divergent.
    """
    if not text_a or not text_b:
        return 0.0
    ca, cb = Counter(text_a), Counter(text_b)
    na, nb = len(text_a), len(text_b)
    alphabet = set(ca) | set(cb)
    js = 0.0
    for ch in alphabet:
        p = ca.get(ch, 0) / na
        q = cb.get(ch, 0) / nb
        m = 0.5 * (p + q)
        if m <= 0.0:
            continue
        if p > 0.0:
            js += 0.5 * p * math.log(p / m)
        if q > 0.0:
            js += 0.5 * q * math.log(q / m)
    # Numerical safety: clamp to [0, ln2]
    if js < 0.0:
        js = 0.0
    elif js > math.log(2):
        js = math.log(2)
    return js


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def compute_per_query(input_text: str, output_text: str) -> List[Dict]:
    """Return a list of metric dicts.

    Each dict has keys: {name, value, unit, label, method, caveat}. The order
    is fixed so the UI can render predictably. None of these values feed
    eight-law scoring or council fusion.
    """
    input_text = input_text or ""
    output_text = output_text or ""

    h_in = _shannon_entropy_bits_per_char(input_text)
    h_out = _shannon_entropy_bits_per_char(output_text)
    gz_in = _gzip_compression_ratio(input_text)
    gz_out = _gzip_compression_ratio(output_text)
    js = _js_divergence_chars(input_text, output_text)

    metrics: List[Dict] = [
        {
            "name": "shannon_entropy_input",
            "value": round(h_in, 4),
            "unit": "bits/char",
            "label": "COMPUTED",
            "method": "Shannon H = -Σ p log₂ p over input char distribution",
            "caveat": None,
        },
        {
            "name": "shannon_entropy_output",
            "value": round(h_out, 4),
            "unit": "bits/char",
            "label": "COMPUTED",
            "method": "Shannon H = -Σ p log₂ p over output char distribution",
            "caveat": None,
        },
        {
            "name": "gzip_ratio_input",
            "value": round(gz_in, 4),
            "unit": "(ratio)",
            "label": "COMPUTED",
            "method": "len(gzip(utf8(input))) / len(utf8(input)) — Kolmogorov upper bound proxy",
            "caveat": None,
        },
        {
            "name": "gzip_ratio_output",
            "value": round(gz_out, 4),
            "unit": "(ratio)",
            "label": "COMPUTED",
            "method": "len(gzip(utf8(output))) / len(utf8(output)) — Kolmogorov upper bound proxy",
            "caveat": None,
        },
        {
            "name": "js_divergence_input_output",
            "value": round(js, 4),
            "unit": "nats",
            "label": "COMPUTED",
            "method": "Jensen-Shannon divergence between input & output char distributions",
            "caveat": None,
        },
        {
            "name": "landauer_floor_per_bit",
            "value": LANDAUER_FLOOR_J_PER_BIT,
            "unit": "J/bit @ T=300K",
            "label": "PHYSICAL_LAW",
            "method": "k_B · T · ln(2) — Landauer 1961, validated for physical bit-erasure substrates",
            "caveat": (
                "Real thermodynamic floor only on physical substrates (electronics, "
                "biological membranes, etc.). Does NOT directly translate to cognitive "
                "operations at macro scale — that step is the ANALOGY below."
            ),
        },
        {
            "name": "lie_cost_anchor",
            "value": LIE_COST_CALIBRATION,
            "unit": "(dimensionless calibration)",
            "label": "ANALOGY",
            "method": "Calibration anchor — PHYSICS_CONSTANTS.md §1.3 «計算嘗試»",
            "caveat": ANALOGY_CAVEAT,
        },
        {
            "name": "freedom_loss_entropy_anchor",
            "value": FREEDOM_LOSS_ENTROPY_CALIBRATION,
            "unit": "(dimensionless calibration)",
            "label": "ANALOGY",
            "method": "Calibration anchor — PHYSICS_CONSTANTS.md §1.1 «計算嘗試»",
            "caveat": ANALOGY_CAVEAT,
        },
    ]
    return metrics


def to_event_payload(input_text: str, output_text: str) -> Dict:
    """Wrap metrics in a payload for the `physics_compute` SSE event.

    Frontend reads payload['metrics'] + payload['display_label'].
    The display_label string is what the UI MUST show on the small dev-only
    line — it embeds the honesty caveat at top level so it cannot be stripped.
    """
    return {
        "display_label": "物理計算 dev-only · 唔影響 LLM 判斷",
        "metrics": compute_per_query(input_text, output_text),
    }
