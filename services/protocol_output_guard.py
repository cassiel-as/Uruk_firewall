"""Deterministic epistemic boundaries for protocol constants."""
from __future__ import annotations

from typing import Any, Dict, Tuple


LIE_COST_BOUNDARY = (
    "先講清楚證據層級：`LIE_COST = 5.85` 係 URUK 內部嘅操作性、正規化中央估計，"
    "唔係由 Landauer 嘅 `kT ln 2` 直接推導出嚟嘅 SI 物理常數。Landauer 原理只支持"
    "『不可逆資訊擦除必有非零物理代價』；5.85 目前來自協議採用嘅成本分解 "
    "`1 + 4 + 0.85`，誠實範圍係約 `4.0–7.0`。歷史相變案例係應用／一致性檢查，"
    "唔等於已完成獨立實證校準。"
)

FREEDOM_LOSS_BOUNDARY = (
    "`FREEDOM_LOSS_ENTROPY = 8.19` 同樣係 URUK 內部用嚟追蹤『外部格式化收窄"
    "一個人可維持嘅座標／選擇空間』嘅操作性參數，唔係已量得嘅自然常數。佢同"
    " `LIE_COST` 嘅關係係代價帳本上嘅轉移／累積關係：維持外部敘事嘅成本可以落到"
    "接收者嘅認知負荷同自由收窄；但目前冇足夠實證支持將 `8.19 / 5.85` 當成普世固定比例。"
)


def enforce_protocol_output_boundaries(query: str, answer: str) -> Tuple[str, Dict[str, Any]]:
    """Prepend a canonical boundary when a response discusses LIE_COST/Landauer."""
    query_lower = str(query or "").casefold()
    answer = str(answer or "").strip()
    lie_relevant = "lie_cost" in query_lower or "landauer" in query_lower or "藍道爾" in query_lower
    freedom_relevant = "freedom_loss_entropy" in query_lower or "8.19" in query_lower
    relevant = lie_relevant or freedom_relevant
    if not relevant:
        return answer, {"active": False, "rules": [], "changed": False}

    lie_already_bounded = any(
        marker in answer.casefold()
        for marker in (
            "唔係由 landauer", "不是由 landauer", "not directly derived from landauer",
            "唔係嚴格", "不是嚴格", "operational estimate", "操作性",
        )
    )
    freedom_already_bounded = (
        "8.19" in answer
        and any(marker in answer.casefold() for marker in (
            "操作性", "operational", "唔係已量得", "不是已测得", "not a measured",
        ))
    )
    boundaries = []
    if lie_relevant and not lie_already_bounded:
        boundaries.append(LIE_COST_BOUNDARY)
    if freedom_relevant and not freedom_already_bounded:
        boundaries.append(FREEDOM_LOSS_BOUNDARY)
    boundary_text = "\n\n".join(boundaries)
    provider_unavailable = "所有可用大型模型都在冷卻或受速率限制" in answer
    changed = provider_unavailable or bool(boundaries)
    if provider_unavailable:
        guarded = boundary_text
    else:
        guarded = answer if not boundaries else f"{boundary_text}\n\n{answer}".strip()
    return guarded, {
        "active": True,
        "rules": [
            rule for enabled, rule in (
                (lie_relevant, "lie_cost_epistemic_boundary"),
                (freedom_relevant, "freedom_loss_epistemic_boundary"),
            ) if enabled
        ],
        "changed": changed,
        "provider_fallback_replaced": provider_unavailable,
        "classification": "operational_estimate_not_strict_landauer_derivation",
    }
