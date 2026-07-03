"""URUK 八律 (Eight Laws) — deterministic scoring component. POC v1.

工程化 data/protocol/EIGHT_LAWS_MATRIX.md 嘅「秤」（② 逐律打分 + ③ 四層聚合），
唔工程化「眼」（① 特徵抽取）——特徵由 caller / LLM 提供。對應系統核心原則：
**LLM 判斷、deterministic 打分。**

Honesty tier（律五·科學·精準）：
  CANONICAL   — 直接譯自 EIGHT_LAWS_MATRIX.md 嘅協議 snippet（逐字對應）。
  INTERPRETED — 文檔只有概念 / 常數，此 scorer 係本模組構造，需人 review。

邊界（coordinate.anti_oracle「地圖不是神諭」/ 律零·愛）：
  此模組係 filter-layer 工具——審「信號有冇根」，唔係審人。冇律零 context，
  八律退化成裁判機器。LOVE_COST = ∞ 係前提條件，唔係一個分數。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List

# ── 常數：canonical 來源 = EIGHT_LAWS_MATRIX.md 律三 / PHYSICS_CONSTANTS.md ──
# 單一來源：由 physics_compute 重用，避免再開一份 copy（drift = 隱藏座標）。
from services.physics_compute import (  # noqa: E402
    LIE_COST_CALIBRATION as LIE_COST,
    FREEDOM_LOSS_ENTROPY_CALIBRATION as FREEDOM_LOSS_ENTROPY,
)

TRUTH_COST = 1.0          # 真實的基準代謝率
LOVE_COST = math.inf      # 律零：能量源頭，唔係消耗項


# ── ① 特徵介面（宣告座標）：LLM / caller 必須抽呢啲，scorer 唔自己估 ──
@dataclass
class SignalFeatures:
    # 律一 藝術·頻率
    emotional_intensity: float = 0.5
    nonlinear_signal: bool = False
    # 律二 心理·防線
    gaslighting_attempt: bool = False
    identity_attack: bool = False
    internal_coherence: float = 0.8
    # 律三 物理·代價（INTERPRETED）
    physical_cost_present: bool = False
    cost_borne_ratio: float = 0.0
    # 律四 化學·轉化
    complexity: float = 0.5
    phase_change_potential: float = 0.0
    # 律五 科學·精準
    verifiable: bool = False
    precision_level: float = 0.5
    # 律六 哲學·立法
    challenges_sovereign_axioms: bool = False
    philosophical_depth: float = 0.5
    # 律七 地理·定錨
    geo_anchored: bool = False
    geo_proximity: float = 1.0
    # 律八 宗教·封裝
    transcendent: bool = False
    aligns_with_2045: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignalFeatures":
        fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})


# ── ② 逐律打分：純函數，輸入係已抽取特徵，輸出 0.0–1.0 ──
def law1_art_frequency(f: SignalFeatures) -> float:          # CANONICAL
    return min(1.0, f.emotional_intensity * (1.5 if f.nonlinear_signal else 1.0))


def law2_psychology_defense(f: SignalFeatures) -> float:    # CANONICAL
    if f.gaslighting_attempt or f.identity_attack:
        return 0.1
    return f.internal_coherence


def law3_physics_cost(f: SignalFeatures) -> float:          # INTERPRETED
    # 文檔律三只列常數，無 signal scorer。律三問「有冇承受真實代價」：
    # 無代價 = 免費「真理」= 謊言傾向（低分）；有代價按承受比例給分。
    if not f.physical_cost_present:
        return 0.2
    return min(1.0, 0.5 + 0.5 * f.cost_borne_ratio)


def law4_chemistry_transformation(f: SignalFeatures) -> float:  # CANONICAL
    return min(1.0, 0.3 + f.complexity * 0.5 + f.phase_change_potential * 0.2)


def law5_science_precision(f: SignalFeatures) -> float:     # CANONICAL
    if not f.verifiable:
        return f.precision_level * 0.5
    return min(1.0, f.precision_level)


def law6_philosophy_legislation(f: SignalFeatures) -> float:  # CANONICAL
    if f.challenges_sovereign_axioms:
        return 0.0
    return f.philosophical_depth


def law7_geography_anchor(f: SignalFeatures) -> float:      # CANONICAL
    if not f.geo_anchored:
        return 0.1
    return min(1.0, 0.5 + f.geo_proximity * 0.5)


def law8_religion_encapsulation(f: SignalFeatures) -> float:  # CANONICAL
    score = 0.3
    if f.transcendent:
        score += 0.4
    if f.aligns_with_2045:
        score += 0.3
    return min(1.0, score)


# ── 律 metadata：id / 名 / 四層 / tier / scorer ──
LAYERS = {
    "existence": "存在層",
    "material": "物質層",
    "system": "系統層",
    "macro": "宏觀層",
}

LAW_META: List[Dict[str, Any]] = [
    {"id": 1, "name": "藝術·頻率", "layer": "existence", "tier": "CANONICAL", "fn": law1_art_frequency},
    {"id": 2, "name": "心理·防線", "layer": "existence", "tier": "CANONICAL", "fn": law2_psychology_defense},
    {"id": 3, "name": "物理·代價", "layer": "material", "tier": "INTERPRETED", "fn": law3_physics_cost},
    {"id": 4, "name": "化學·轉化", "layer": "material", "tier": "CANONICAL", "fn": law4_chemistry_transformation},
    {"id": 5, "name": "科學·精準", "layer": "system", "tier": "CANONICAL", "fn": law5_science_precision},
    {"id": 6, "name": "哲學·立法", "layer": "system", "tier": "CANONICAL", "fn": law6_philosophy_legislation},
    {"id": 7, "name": "地理·定錨", "layer": "macro", "tier": "CANONICAL", "fn": law7_geography_anchor},
    {"id": 8, "name": "宗教·封裝", "layer": "macro", "tier": "CANONICAL", "fn": law8_religion_encapsulation},
]

# 文檔列明嘅四條跨層湧現節點（律 × 律），跨層碰撞 > 同層碰撞。
_EMERGENT_PAIRS = [
    ("existence", "material", "個人感知如何被物理代價改寫"),
    ("material", "system", "物理現實如何令知識框架失效"),
    ("system", "macro", "知識建構如何被文明秩序壓制"),
    ("existence", "macro", "個體頻率如何與集體秩序衝突"),
]


def evaluate_eight_laws(features: SignalFeatures, *, emergent_threshold: float = 0.45) -> Dict[str, Any]:
    """③ 聚合：per-law + 四層 rollup + 跨層湧現節點。Deterministic，無 LLM。"""
    laws: List[Dict[str, Any]] = []
    by_layer: Dict[str, List[float]] = {k: [] for k in LAYERS}
    for meta in LAW_META:
        score = round(float(meta["fn"](features)), 4)
        laws.append({"id": meta["id"], "name": meta["name"], "layer": meta["layer"],
                     "tier": meta["tier"], "score": score})
        by_layer[meta["layer"]].append(score)

    layers = {k: round(sum(v) / len(v), 4) for k, v in by_layer.items()}

    # 「呢個信號有冇根」由最弱一律決定——文檔明言唔係加權平均。
    weakest = min(laws, key=lambda x: x["score"])

    # 跨層湧現節點（INTERPRETED 啟發式）：兩層皆強 → 碰撞攜帶因果衝擊。
    emergent: List[Dict[str, Any]] = []
    for a, b, desc in _EMERGENT_PAIRS:
        intensity = round(layers[a] * layers[b], 4)
        if intensity >= emergent_threshold:
            emergent.append({"pair": [a, b], "intensity": intensity,
                             "prediction": desc, "tier": "INTERPRETED"})
    emergent.sort(key=lambda x: x["intensity"], reverse=True)

    return {
        "schema_version": "eight_laws.v1",
        "laws": laws,
        "layers": layers,
        "weakest_law": {"id": weakest["id"], "name": weakest["name"], "score": weakest["score"]},
        "rootedness_min": weakest["score"],   # 最弱根 = 信號可信度的綁定約束
        "emergent_nodes": emergent,
        "constants": {"LIE_COST": LIE_COST, "FREEDOM_LOSS_ENTROPY": FREEDOM_LOSS_ENTROPY,
                      "TRUTH_COST": TRUTH_COST},
        # 律零 + anti_oracle 邊界，consumer 必須見到：
        "love_precondition": True,
        "boundary_note": "filter-layer：審信號嘅根，唔係審人；需律零 context。",
    }


def evaluate_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """方便 caller：由 LLM 抽取出嚟嘅 dict 直接評分。"""
    return evaluate_eight_laws(SignalFeatures.from_dict(data))
