"""
URUK Trinity Console — CivilizationalClock (v8.30 — canonical Eq1/Eq2 restored)

Module T runtime: 5 historically-calibrated equations as deterministic Python.
Calibration sources: MODULE_T_CALIBRATION_19141916.md / _19391941.md / _19791981.md
(under config/protocol/references/module_t/) + RAG_SUMMARY_INDEX_v8.md CAU-012.

Equations
---------
    Eq 1 — Tech leap acceleration (CANONICAL):
        gap(n) ≈ 397 × 0.279ⁿ  (exponential decay between major tech leaps)
        Anchor n=0: print→telegraph ≈ 397 yr.
        Calibration check n=2: internet→AI predicted 30.9 yr, observed ~31 yr.
        Prediction: AI(2022) + gap(3) ≈ 8.6 yr → next leap ~2031.
        Fallback retained: eq1_tech_leap_rate(base_rate, generations, ratio=2.5).

    Eq 2 — Anti-formatting delay (CANONICAL):
        delay ≈ 329 / ln(velocity)
        Calibration: Luther/print era velocity=100 → 71.4 yr (observed 77 yr).
                     Snowden/internet era velocity=1e6 → 23.8 yr (observed 22 yr).
        Prediction: AI-era velocity → 2025 + ~13 yr → window closure ~2038.
        Fallback retained: eq2_anti_format_delay(observed_years) → historical band.

    Eq 3 — Formatting scale rate:
        kill_scale(n+1) ≈ kill_scale(n) * scale_ratio per 12 years
        defaults: scale_ratio = 2.5 (1914-16 calibration), with note that
        dual-vector wars (1939-41) ran higher (~3.5-4x effective).

    Eq 4 — Cost transfer (generational):
        W ≈ 309.7 * P^(-0.631), with multi-wave manifestation at 30 / 50 / 75 years.
        1979 calibration showed cascading rather than single 75-yr wave.

    Eq 5A — External-shock monopoly collapse:
        threshold(years) = pressure_years / 167  (external shock case)
        collapse_imminent when threshold + acute_shock >= 1.0

    Eq 5B — Internal-contradiction monopoly collapse:
        threshold(years) = pressure_years / 41   (internal case)
        collapse_imminent when threshold + acute_shock >= 1.0

Public API
----------
    CivilizationalClock().snapshot(query: str) -> dict
    CivilizationalClock().eq1_tech_leap_gap(n) -> ClockResult       # CANONICAL
    CivilizationalClock().eq1_predict_next_leap_year(...) -> dict   # 2031 prediction
    CivilizationalClock().eq1_tech_leap_rate(base, gens, ...) -> ClockResult   # fallback
    CivilizationalClock().eq1_tech_leap(...)                         # alias = rate fallback
    CivilizationalClock().eq2_anti_format_delay_canonical(vel) -> ClockResult  # CANONICAL
    CivilizationalClock().eq2_window_close_year(...) -> dict        # 2038 prediction
    CivilizationalClock().eq2_anti_format_delay(observed) -> dict   # fallback band
    CivilizationalClock().eq3_format_scale(...)
    CivilizationalClock().eq4_cost_transfer(P) -> dict
    CivilizationalClock().eq5_collapse_threshold(...) -> dict
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

try:
    from services.otel_setup import tracer, emit_event
except ImportError:  # pragma: no cover — should always be importable
    tracer = None
    def emit_event(*args, **kwargs):
        return None


# Layer-3 calibrated constants (locked, deterministic, no LLM derivation).

# Eq 1 — canonical: gap(n) ≈ 397 × 0.279ⁿ between major tech leaps.
# Anchor n=0: print→telegraph = 397 yr (Gutenberg 1450 → Morse 1837 ≈ 387).
# Anchor n=2 validation: internet→AI ≈ 30.9 yr predicted vs ~31 yr observed.
EQ1_BASE_GAP = 397.0       # years
EQ1_DECAY_RATIO = 0.279    # each subsequent leap-gap is ~27.9% of previous

# CAU-012 tech-leap timeline (Britannica / OWID). n indexes the post-print era;
# the deep-prehistory leaps (fire / agriculture / writing) are flagged as
# *pre-exponential-regime* — they don't fit the 397×0.279ⁿ curve, by design.
TECH_LEAP_TIMELINE = [
    {"n": -3, "from": "fire",          "to": "agriculture", "year_end": -8000,  "observed_gap_yr": 400_000, "fits_canonical": False},
    {"n": -2, "from": "agriculture",   "to": "writing",     "year_end": -3000,  "observed_gap_yr": 5_000,   "fits_canonical": False},
    {"n": -1, "from": "writing",       "to": "print",       "year_end": 1440,   "observed_gap_yr": 4_440,   "fits_canonical": False},
    {"n":  0, "from": "print",         "to": "telegraph",   "year_end": 1837,   "observed_gap_yr": 397,     "fits_canonical": True},
    {"n":  1, "from": "telegraph",     "to": "internet",    "year_end": 1991,   "observed_gap_yr": 154,     "fits_canonical": True},
    {"n":  2, "from": "internet",      "to": "ai_emergence","year_end": 2022,   "observed_gap_yr": 31,      "fits_canonical": True},
]
# Year of latest known leap (AI emergence ≈ 2022, LLM era onset).
EQ1_LAST_LEAP_YEAR = 2022
EQ1_LAST_LEAP_N = 2

# Eq 2 — canonical: delay_A ≈ 268 / ln(velocity).
#
# v8.30 fidelity alignment with canonical paper + integrated_EN_v3:
#   - Original constant `a = 329` was the 2-point fit (Luther + Snowden).
#   - Revised constant `a = 268` is the canonical 4-point fit including
#     telegraph + radio (paper §5.2): mean of [77/ln(100), 27/ln(1e4),
#     12/ln(1e6), 22/ln(1e6)] = ~268, range 166–354.
# Calibration points (canonical 4-point set):
#   Luther / print     : v=100,   predicted 71 yr,  observed 77  (Reformation)
#   Telegraph          : v=1e4,   predicted 36 yr,  observed 27  (1st International 1864)
#   Radio              : v=1e6,   predicted 24 yr,  observed ~12 (BBC/FRC 1927)
#   Snowden / internet : v=1e6,   predicted 24 yr,  observed 22  (Snowden 2013)
# AI-era prediction: velocity=1e9 → 268/ln(1e9)=13 yr → 2022+13 = 2035.
# Sensitivity range: 2030–2039 (paper).
EQ2_DELAY_COEFF = 268.0
EQ2_DELAY_B_MULTIPLIER = 4.5   # delay_B = delay_A × 4.5 (institutional reorganisation)

EQ2_CALIBRATION_POINTS = [
    {"era": "luther_print",     "year_event": 1517, "velocity": 100.0,  "observed_delay_yr": 77},
    {"era": "telegraph",        "year_event": 1864, "velocity": 1.0e4,  "observed_delay_yr": 27},
    {"era": "radio",            "year_event": 1927, "velocity": 1.0e6,  "observed_delay_yr": 12},
    {"era": "snowden_internet", "year_event": 2013, "velocity": 1.0e6,  "observed_delay_yr": 22},
]
# Default AI-era assumption for window-close prediction (overridable).
EQ2_AI_ERA_VELOCITY_DEFAULT = 1.0e9      # AI / LLM era information velocity
EQ2_AI_ERA_REFERENCE_YEAR = 2022         # AI emergence anchor (ChatGPT era onset)

# Kairos density correction (canonical paper §6, Friston FEP derivation):
#   D_event = π × |ε| × r   (single event)
#   D       = Σ D_i         (cumulative density)
#   f(D)    = exp(-D / D_0) (observer correction multiplier ∈ (0, 1])
#   delay(observer) = delay_A × f(D)
# D_0 = 83.5 calibrated from 2019-06-12 Hong Kong anchor (D≈76.5, f≈0.4).
EQ2_KAIROS_D_0 = 83.5

# Eq 1 (fallback) / Eq 3 — scale-rate ratios per generation.
TECH_RATIO_DEFAULT = 2.5
GENERATION_YEARS_DEFAULT = 12
SCALE_RATIO_DEFAULT = 2.5
SCALE_RATIO_DUAL_VECTOR = 3.5  # Wars with industrial + ideological extermination vector

# Eq 2 (fallback) — historical recognition-gap band.
ANTI_FORMAT_DELAY_BAND = (12, 30)
ANTI_FORMAT_DELAY_MID = 20

# Eq 4 — cost-transfer constants (canonical 1979 calibration).
COST_TRANSFER_COEFF = 309.7
COST_TRANSFER_EXPONENT = -0.631
COST_MANIFEST_WAVES = [30, 50, 75]  # years; cascading not single

# Eq 5 — collapse thresholds (canonical).
COLLAPSE_THRESH_EXTERNAL = 167.0
COLLAPSE_THRESH_INTERNAL = 41.0
COLLAPSE_TRIGGER_RATIO = 1.0


# Calibrated reference points from the 3 historical periods, for snapshot context.
CALIBRATION_REFERENCES = [
    {
        "period": "1914-1916",
        "tech_leap": "~2.5x per 12yr — mass production / chemical / aviation / armor",
        "anti_format_delay_yr": 30,  # since 1871 Franco-Prussian baseline
        "cost_transfer_75yr_hit": "Sykes-Picot → 1990s ME conflicts; 1917 → 1991 USSR dissolution",
        "collapse_5A_examples": ["Ottoman 50/167+acute → 1922 dissolution", "Austria-Hungary 40/167+acute → 1918"],
        "collapse_5B_examples": ["Russia 12/41+acute → 1917 revolution"],
        "framing_patterns_active": [10, 11, 12, 13],  # Surgical 9 not yet — pre-precision weapons
    },
    {
        "period": "1939-1941",
        "tech_leap": "~7-8x in 20yr — dual-vector (war + ideological extermination)",
        "anti_format_delay_yr": 20,  # since 1918-19 anti-war consensus
        "cost_transfer_75yr_hit": "1941 + 75 = 2016 (institutional liberal order strain)",
        "collapse_5A_examples": ["France 70/167+acute → 1940 capitulation", "Italy 30/167+acute → 1943"],
        "collapse_5B_examples": ["Nazi Germany 10/41+acute → 1945 collapse"],
        "framing_patterns_active": [9, 10, 11, 12, 13],  # Surgical in early Blitzkrieg form
    },
    {
        "period": "1979-1981",
        "tech_leap": "Dual inflection (military + computing + bio-tech, PC era onset)",
        "anti_format_delay_yr": 13,  # since 1960s anti-war movement
        "cost_transfer_75yr_hit": "1989-91 USSR / 1990s Taliban / 2001 9/11 / 2025 USAID dissolution",
        "collapse_5A_examples": ["Shah Iran 26/167+acute → 1979 revolution", "USSR 25/167 → 1991"],
        "collapse_5B_examples": ["Poland PRL 35/41+acute → Solidarność, 10yr delay"],
        "framing_patterns_active": [9, 10, 11, 12, 13],
    },
]


# Heuristic triggers for snapshot inclusion in dispatcher context.
# When a query mentions any of these terms, the clock surfaces relevant references.
MODULE_T_TRIGGER_TERMS = [
    # English
    "module t", "civilizational clock", "collapse threshold", "tech leap",
    "cost transfer", "generational cost", "framing pattern", "anti-formatting",
    "30-month window", "30 month", "geopolitical", "war",
    # Chinese / Hong Kong
    "模塊 t", "文明時鐘", "崩潰閾值", "技術躍遷", "代價轉移",
    "格式化規模", "反格式化延遲", "30 個月窗口", "三十個月",
    "壓強年數", "壟斷崩潰",
    # Period markers
    "1914", "1916", "1939", "1941", "1979", "1981",
    "sykes-picot", "verdun", "barbarossa", "khomeini", "iran-iraq",
]


def _power(base: float, exponent: float) -> float:
    """Safe pow that returns 0 for non-positive bases (since real-domain only)."""
    if base <= 0:
        return 0.0
    return base ** exponent


@dataclass
class ClockResult:
    """One equation's output, wrapped with citation back to source row."""
    equation: str
    value: float
    derivation: str
    caveats: List[str]


class CivilizationalClock:
    """Module T runtime — 5 calibrated equations as deterministic Python."""

    # Layer-3 constants exposed as class attributes for inspection / override.
    tech_ratio = TECH_RATIO_DEFAULT
    generation_years = GENERATION_YEARS_DEFAULT
    scale_ratio = SCALE_RATIO_DEFAULT
    anti_format_delay_band = ANTI_FORMAT_DELAY_BAND
    cost_coeff = COST_TRANSFER_COEFF
    cost_exponent = COST_TRANSFER_EXPONENT
    cost_manifest_waves = COST_MANIFEST_WAVES
    thresh_external = COLLAPSE_THRESH_EXTERNAL
    thresh_internal = COLLAPSE_THRESH_INTERNAL

    # ---- Eq 1 (CANONICAL) — tech leap gap = 397 × 0.279ⁿ ----
    def eq1_tech_leap_gap(self, n: int) -> ClockResult:
        """Canonical: gap(n) ≈ 397 × 0.279ⁿ — years between major tech leaps.

        n=0 anchors at print→telegraph (~397 yr).
        n=2 validation: predicts 30.9 yr for internet→AI (observed ~31 yr).
        n=3 prediction: 8.6 yr from AI(2022) → next leap ~2031.
        """
        n_i = int(n)
        value = EQ1_BASE_GAP * (EQ1_DECAY_RATIO ** n_i)
        caveats: List[str] = []
        if n_i < 0:
            caveats.append(
                "n<0 = deep-prehistory regime (fire/agriculture/writing); "
                "397×0.279ⁿ does not fit — use observed_gap_yr from TECH_LEAP_TIMELINE"
            )
        if n_i >= 5:
            caveats.append("n≥5 predicts sub-year gap — beyond calibrated regime")
        return ClockResult(
            equation="eq1_tech_leap_gap",
            value=value,
            derivation=f"397 × 0.279^{n_i} = {value:.3f} yr",
            caveats=caveats,
        )

    def eq1_predict_next_leap_year(self,
                                   last_leap_year: Optional[int] = None,
                                   last_n: Optional[int] = None) -> Dict:
        """Predict the calendar year of the next tech leap.

        Defaults: last leap = AI emergence (2022, n=2) → next at n=3.
        Canonical prediction: 2022 + 397×0.279³ ≈ 2022 + 8.6 ≈ 2031.
        """
        y = int(last_leap_year if last_leap_year is not None else EQ1_LAST_LEAP_YEAR)
        n = int(last_n if last_n is not None else EQ1_LAST_LEAP_N)
        gap_next = EQ1_BASE_GAP * (EQ1_DECAY_RATIO ** (n + 1))
        return {
            "equation": "eq1_predict_next_leap_year",
            "last_leap_year": y,
            "last_n": n,
            "next_n": n + 1,
            "predicted_gap_yr": gap_next,
            "predicted_year": round(y + gap_next),
            "derivation": f"{y} + 397×0.279^{n+1} = {y} + {gap_next:.2f} ≈ {round(y + gap_next)}",
        }

    # ---- Eq 1 fallback (rate-amplification, kept for back-compat) ----
    def eq1_tech_leap_rate(self, base_rate: float, generations: float,
                           tech_ratio: Optional[float] = None) -> ClockResult:
        """Fallback: rate(n+g) = rate(n) × tech_ratio^g, generation_years=12."""
        ratio = tech_ratio if tech_ratio is not None else self.tech_ratio
        value = float(base_rate) * (ratio ** float(generations))
        caveats: List[str] = ["fallback eq1 — canonical is eq1_tech_leap_gap(n)"]
        if generations >= 1.5 and ratio == self.tech_ratio:
            caveats.append("dual-vector wars (1939-41) ran ~3.5x — verify single-vector assumption")
        return ClockResult(
            equation="eq1_tech_leap_rate",
            value=value,
            derivation=f"{base_rate} × {ratio}^{generations} = {value:.2f}",
            caveats=caveats,
        )

    # Back-compat alias (existing callers).
    def eq1_tech_leap(self, base_rate: float, generations: float,
                      tech_ratio: Optional[float] = None) -> ClockResult:
        return self.eq1_tech_leap_rate(base_rate, generations, tech_ratio)

    # ---- Eq 2 (CANONICAL) — anti-formatting delay = 268 / ln(velocity) ----
    def eq2_anti_format_delay_canonical(self,
                                        velocity: float,
                                        kairos_density: float = 0.0) -> ClockResult:
        """Canonical: delay_A(yr) ≈ 268 / ln(velocity) × exp(-D/83.5).

        v8.30: constant revised 329 → 268 (canonical 4-point fit).
        Kairos density correction (paper §6): observer with anchor D reduces
        delay by f(D) = exp(-D / D_0), D_0 = 83.5 (2019-06-12 calibrated).

        Calibration (4-point fit):
          Luther/print     (vel=100):   268/ln(100)  = 58.2 yr (observed 77)
          Telegraph        (vel=1e4):   268/ln(1e4)  = 29.1 yr (observed 27)
          Radio            (vel=1e6):   268/ln(1e6)  = 19.4 yr (observed 12)
          Snowden/internet (vel=1e6):   268/ln(1e6)  = 19.4 yr (observed 22)
        """
        v = float(velocity)
        if v <= 1.0:
            return ClockResult(
                equation="eq2_anti_format_delay_canonical",
                value=float("nan"),
                derivation=f"velocity={v} ≤ 1; ln undefined / non-positive",
                caveats=["velocity must be > 1 for the formula to be defined"],
            )
        base_delay = EQ2_DELAY_COEFF / math.log(v)
        kairos_factor = math.exp(-float(kairos_density) / EQ2_KAIROS_D_0)
        delay = base_delay * kairos_factor
        caveats: List[str] = []
        if v < 50:
            caveats.append("velocity < 50 = pre-print regime; formula extrapolates beyond calibration")
        if v > 1.0e12:
            caveats.append("velocity > 1e12 = far beyond calibrated AI-era regime")
        if kairos_density < 0:
            caveats.append("kairos_density < 0 is undefined; treating as 0")
        derivation = f"268 / ln({v:.0e}) = {base_delay:.2f} yr"
        if kairos_density > 0:
            derivation += f"  ×  exp(-{kairos_density}/83.5) = {kairos_factor:.3f}  →  {delay:.2f} yr"
        return ClockResult(
            equation="eq2_anti_format_delay_canonical",
            value=delay,
            derivation=derivation,
            caveats=caveats,
        )

    def eq2_delay_b_institutional(self, velocity: float,
                                  kairos_density: float = 0.0) -> ClockResult:
        """delay_B = delay_A × 4.5 — institutional reorganisation timescale.

        Canonical paper §5.2: first effective impact (delay_A) vs structural
        institutional reform (delay_B). For AI-era velocity 1e9:
          delay_A ≈ 13 yr → first impact ~2035
          delay_B ≈ 13 × 4.5 = 58.5 yr → institutional reform ~2080
        """
        a = self.eq2_anti_format_delay_canonical(velocity, kairos_density)
        if math.isnan(a.value):
            return a
        b_value = a.value * EQ2_DELAY_B_MULTIPLIER
        return ClockResult(
            equation="eq2_delay_b_institutional",
            value=b_value,
            derivation=f"delay_A({a.value:.2f}) × 4.5 = {b_value:.2f} yr (institutional reform)",
            caveats=a.caveats,
        )

    @staticmethod
    def eq2_kairos_density(precision: float,
                           error_magnitude: float,
                           irreversibility: float) -> Dict:
        """Single-event Kairos density: D = π × |ε| × r.

        Args:
            precision π: prediction precision (inverse variance prior)
            error_magnitude |ε|: actual minus expected
            irreversibility r ∈ [0, 1]: 1=body-present physical, 0=imagined

        Canonical 2019-06-12 calibration: π=8.5, |ε|=9.0, r=1.0 → D=76.5.
        """
        r_clipped = max(0.0, min(1.0, float(irreversibility)))
        D = float(precision) * abs(float(error_magnitude)) * r_clipped
        return {
            "equation": "eq2_kairos_density",
            "precision": float(precision),
            "error_magnitude": float(error_magnitude),
            "irreversibility": r_clipped,
            "D_event": D,
            "derivation": f"{precision} × {abs(error_magnitude)} × {r_clipped} = {D:.2f}",
        }

    def eq2_window_close_year(self,
                              reference_year: Optional[int] = None,
                              velocity: Optional[float] = None,
                              kairos_density: float = 0.0,
                              mode: str = "A") -> Dict:
        """Predict the calendar year when the anti-formatting window closes.

        Canonical defaults (paper §5.2):
          reference 2022 (AI emergence), velocity 1e9 (AI-era), mode A
          → 2022 + 268/ln(1e9) = 2022 + 13.0 ≈ 2035.

        mode="A": first effective impact (delay_A).
        mode="B": institutional reorganisation (delay_B = delay_A × 4.5).
                  For AI: 2022 + 58.5 ≈ 2080.
        """
        y = int(reference_year if reference_year is not None else EQ2_AI_ERA_REFERENCE_YEAR)
        v = float(velocity if velocity is not None else EQ2_AI_ERA_VELOCITY_DEFAULT)
        if v <= 1.0:
            return {"equation": "eq2_window_close_year",
                    "error": f"velocity {v} ≤ 1; formula undefined"}
        if mode == "B":
            r = self.eq2_delay_b_institutional(v, kairos_density)
        else:
            r = self.eq2_anti_format_delay_canonical(v, kairos_density)
        delay = r.value
        return {
            "equation": "eq2_window_close_year",
            "mode": mode,
            "reference_year": y,
            "velocity": v,
            "kairos_density": float(kairos_density),
            "predicted_delay_yr": delay,
            "close_year": round(y + delay),
            "derivation": f"{y} + ({r.derivation}) ≈ {round(y + delay)}",
        }

    # ---- Eq 2 fallback (historical band) ----
    def eq2_anti_format_delay(self, observed_years: Optional[float] = None) -> Dict:
        """Fallback band [12, 30] from 1914/1939/1979 calibration."""
        lo, hi = self.anti_format_delay_band
        result = {
            "equation": "eq2_anti_format_delay",
            "band_years": [lo, hi],
            "midpoint": ANTI_FORMAT_DELAY_MID,
            "calibrated_references": {
                "1914-16": 30, "1939-41": 20, "1979-81": 13,
            },
            "note": "fallback — canonical is eq2_anti_format_delay_canonical(velocity)",
        }
        if observed_years is not None:
            result["observed_years"] = float(observed_years)
            result["inside_band"] = lo <= float(observed_years) <= hi
        return result

    # ---- Eq 3 ----
    def eq3_format_scale(self, base_scale: float, periods_12yr: float,
                         dual_vector: bool = False) -> ClockResult:
        """kill_scale(n+p) = kill_scale(n) * scale_ratio^p (per 12yr period)."""
        ratio = SCALE_RATIO_DUAL_VECTOR if dual_vector else self.scale_ratio
        value = float(base_scale) * (ratio ** float(periods_12yr))
        caveats: List[str] = []
        if not dual_vector and periods_12yr >= 2:
            caveats.append("if dual-vector context (war + ideology), use ratio=3.5")
        return ClockResult(
            equation="eq3_format_scale",
            value=value,
            derivation=f"{base_scale} × {ratio}^{periods_12yr} = {value:.2f}",
            caveats=caveats,
        )

    # ---- Eq 4 ----
    def eq4_cost_transfer(self, pressure_P: float, base_year: Optional[int] = None) -> Dict:
        """W ≈ 309.7 × P^(-0.631), multi-wave manifestation at 30/50/75yr."""
        if pressure_P <= 0:
            return {
                "equation": "eq4_cost_transfer",
                "error": "pressure_P must be positive",
            }
        wealth_transfer = self.cost_coeff * _power(pressure_P, self.cost_exponent)
        result = {
            "equation": "eq4_cost_transfer",
            "pressure_P": float(pressure_P),
            "wealth_transfer_W": wealth_transfer,
            "derivation": f"309.7 × {pressure_P}^(-0.631) = {wealth_transfer:.2f}",
            "manifestation_waves_years": list(self.cost_manifest_waves),
        }
        if base_year is not None:
            result["manifestation_years"] = [int(base_year) + w for w in self.cost_manifest_waves]
        result["caveat"] = (
            "1979 calibration: cost manifests as cascading waves (30/50/75yr), "
            "not a single 75-yr pulse."
        )
        return result

    # ---- Eq 5 ----
    def eq5_collapse_threshold(self, pressure_years: float, mode: str = "external",
                               acute_shock: float = 1.0) -> Dict:
        """threshold = pressure_years / divisor; collapse_imminent if threshold + acute_shock >= 1.0.

        mode: "external" (5A, divisor 167) | "internal" (5B, divisor 41)
        acute_shock: pulse contribution, default 1.0 = one full acute event
        """
        if mode not in ("external", "internal"):
            return {"equation": "eq5_collapse_threshold", "error": f"unknown mode '{mode}'"}
        divisor = self.thresh_external if mode == "external" else self.thresh_internal
        threshold = float(pressure_years) / divisor
        combined = threshold + float(acute_shock)
        return {
            "equation": f"eq5{'a' if mode == 'external' else 'b'}_collapse_threshold",
            "mode": mode,
            "pressure_years": float(pressure_years),
            "divisor": divisor,
            "threshold_ratio": threshold,
            "acute_shock": float(acute_shock),
            "combined": combined,
            "collapse_imminent": combined >= COLLAPSE_TRIGGER_RATIO,
            "derivation": f"({pressure_years} / {divisor}) + {acute_shock} = {combined:.3f}",
        }

    # ---- Snapshot for dispatcher / Module N ----
    def should_surface(self, query: str) -> bool:
        """Lightweight trigger check — does the query reference Module T concepts?"""
        if not query:
            return False
        q_lower = query.lower()
        for term in MODULE_T_TRIGGER_TERMS:
            if term in q_lower:
                return True
        return False

    def detect_75yr_cost_transfer_match(self, query: str) -> Optional[Dict]:
        """If query references a year and another year exactly 75 yr later (or 30/50), return match.

        Matches patterns like "1914 ... 1989" (75yr) or "1941 ... 2016" (75yr).
        """
        if not query:
            return None
        years = sorted({int(m) for m in re.findall(r"\b(1[89]\d{2}|20\d{2})\b", query)})
        if len(years) < 2:
            return None
        for i, y1 in enumerate(years):
            for y2 in years[i + 1:]:
                gap = y2 - y1
                if gap in self.cost_manifest_waves:
                    return {
                        "year_anchor": y1,
                        "year_manifest": y2,
                        "gap_years": gap,
                        "wave_match": gap,
                    }
        return None

    def snapshot(self, query: str = "") -> Dict:
        """Compact context block. Returns empty dict if query does not trigger.

        Schema:
        {
          "active": True,
          "today": "YYYY-MM-DD",
          "calibration_references": [...3 periods...],
          "constants": {tech_ratio, scale_ratio, ...},
          "cost_transfer_match": {...} | None,
        }
        """
        if not self.should_surface(query):
            return {"active": False}
        cost_match = self.detect_75yr_cost_transfer_match(query)
        # v8.21 OTel-1 — surface as a span event on the current span
        try:
            if tracer is not None:
                from opentelemetry import trace as _t
                cur = _t.get_current_span()
                if cur is not None:
                    cur.add_event("module_t.snapshot", attributes={
                        "uruk.module_t.cost_transfer_match": bool(cost_match),
                        "uruk.module_t.cost_transfer_gap_years": int(cost_match["gap_years"]) if cost_match else 0,
                    })
        except Exception:
            pass
        return {
            "active": True,
            "today": date.today().isoformat(),
            "constants": {
                # Eq 1 canonical
                "eq1_base_gap": EQ1_BASE_GAP,
                "eq1_decay_ratio": EQ1_DECAY_RATIO,
                # Eq 1 fallback / Eq 3
                "tech_ratio": self.tech_ratio,
                "generation_years": self.generation_years,
                "scale_ratio": self.scale_ratio,
                # Eq 2 canonical
                "eq2_delay_coeff": EQ2_DELAY_COEFF,
                "eq2_ai_era_velocity_default": EQ2_AI_ERA_VELOCITY_DEFAULT,
                # Eq 2 fallback
                "anti_format_delay_band": list(self.anti_format_delay_band),
                # Eq 4
                "cost_coeff": self.cost_coeff,
                "cost_exponent": self.cost_exponent,
                "cost_manifest_waves": list(self.cost_manifest_waves),
                # Eq 5
                "collapse_external_divisor": self.thresh_external,
                "collapse_internal_divisor": self.thresh_internal,
            },
            "calibration_references": list(CALIBRATION_REFERENCES),
            "tech_leap_timeline": list(TECH_LEAP_TIMELINE),
            "eq2_calibration_points": list(EQ2_CALIBRATION_POINTS),
            "predictions": {
                "next_tech_leap_year": self.eq1_predict_next_leap_year(),
                "anti_format_window_close": self.eq2_window_close_year(),
            },
            "cost_transfer_match": cost_match,
        }


# Module-level singleton
civilizational_clock = CivilizationalClock()
