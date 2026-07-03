from services.protocol_output_guard import enforce_protocol_output_boundaries


def test_lie_cost_claim_gets_canonical_epistemic_boundary():
    answer, audit = enforce_protocol_output_boundaries(
        "LIE_COST係咩？點解係5.85？",
        "5.85 由 Landauer 原理嚴格推導。",
    )

    assert audit["active"] is True
    assert audit["changed"] is True
    assert "唔係由 Landauer" in answer
    assert "4.0–7.0" in answer


def test_unrelated_answer_is_unchanged():
    answer, audit = enforce_protocol_output_boundaries("今日天氣？", "未知")

    assert answer == "未知"
    assert audit["active"] is False


def test_lie_cost_boundary_becomes_degraded_answer_when_providers_are_cooling():
    answer, audit = enforce_protocol_output_boundaries(
        "LIE_COST係咩？",
        "目前所有可用大型模型都在冷卻或受速率限制。系統已停止重試。",
    )

    assert audit["provider_fallback_replaced"] is True
    assert "所有可用大型模型" not in answer
    assert "操作性、正規化中央估計" in answer


def test_relation_question_gets_both_operational_boundaries():
    answer, audit = enforce_protocol_output_boundaries(
        "FREEDOM_LOSS_ENTROPY 同 LIE_COST 有咩關係？",
        "目前所有可用大型模型都在冷卻或受速率限制。",
    )

    assert set(audit["rules"]) == {
        "lie_cost_epistemic_boundary", "freedom_loss_epistemic_boundary",
    }
    assert "5.85" in answer
    assert "8.19" in answer
    assert "普世固定比例" in answer
