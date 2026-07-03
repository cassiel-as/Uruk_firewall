from services.world_forecast import forecast_world


def _write_fixture(root, folder, name, text):
    path = root / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(text, encoding="utf-8")


def test_history_only_forecast_uses_internal_causal_records(tmp_path):
    _write_fixture(
        tmp_path,
        "causal_db",
        "CAU-900_TEST_WAR.md",
        "war nuclear military conflict escalation treaty",
    )
    _write_fixture(
        tmp_path,
        "causal_records",
        "CAUSAL_RECORD_TEST.md",
        "attack strike sanctions institutional stress casualty",
    )

    result = forecast_world(input_text="war escalation", data_dir=tmp_path)

    assert result["ok"] is True
    assert result["schema_version"] == "world_forecast.v1"
    assert result["evidence_counts"]["history"] >= 1
    assert result["evidence_counts"]["news"] == 0
    assert result["signals"]["kinetic_risk"] > 0
    assert any(item["coordinate"] == "internal_historical_causal_record" for item in result["evidence"])
    assert "no_live_news_input" in result["warnings"]
    assert any(w.startswith("not_oracle") for w in result["warnings"])


def test_news_filter_flags_single_coordinate_sources(tmp_path):
    _write_fixture(tmp_path, "causal_db", "CAU-901_BASE.md", "policy stability")
    news = [
        {"url": "https://reuters.com/a", "title": "A", "text": "missile attack conflict"},
        {"url": "https://reuters.com/b", "title": "B", "text": "troop movement"},
        {"url": "https://reuters.com/c", "title": "C", "text": "strike casualties"},
    ]

    result = forecast_world(input_text="conflict", data_dir=tmp_path, news_sources=news)

    assert result["evidence_counts"]["news"] == 3
    assert result["news_filter"]["coordinate_count"] == 1
    assert "insufficient_coordinate_diversity" in result["news_filter"]["flags"]


def test_diverse_news_changes_risk_signal(tmp_path):
    _write_fixture(tmp_path, "causal_db", "CAU-902_BASE.md", "policy reform treaty mediation")

    baseline = forecast_world(input_text="regional stability", data_dir=tmp_path)
    news = [
        {"url": "https://reuters.com/a", "title": "Attack", "text": "missile attack war casualties"},
        {"url": "https://apnews.com/b", "title": "Troops", "text": "military troop conflict"},
        {"url": "https://rt.com/c", "title": "Strike", "text": "strike nuclear warning"},
    ]
    with_news = forecast_world(input_text="regional stability", data_dir=tmp_path, news_sources=news)

    assert with_news["evidence_counts"]["news"] == 3
    assert with_news["news_filter"]["coordinate_count"] >= 2
    assert "insufficient_coordinate_diversity" not in with_news["news_filter"]["flags"]
    assert with_news["signals"]["kinetic_risk"] > baseline["signals"]["kinetic_risk"]


def test_no_evidence_keeps_forecast_high_uncertainty(tmp_path):
    result = forecast_world(input_text="unknown future", data_dir=tmp_path)

    assert result["evidence_counts"]["total"] == 0
    assert result["forecast"]["uncertainty"] >= 0.75
    assert "no_evidence_available" in result["warnings"]
    assert "high_uncertainty" in result["warnings"]
