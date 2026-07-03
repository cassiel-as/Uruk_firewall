import json

from services.world_geotimeline import build_geo_timeline, extract_news_geo_events, load_geo_events
from services.world_revision_ledger import append_revision, load_revisions


def _write_world_fixture(root):
    path = root / "world"
    path.mkdir(parents=True, exist_ok=True)
    (path / "historical_events.json").write_text(
        json.dumps(
            {
                "schema_version": "uruk_geo_history.v1",
                "events": [
                    {
                        "id": "evt_a",
                        "date": "1914-06-28",
                        "title": "Sarajevo war trigger",
                        "location": "Sarajevo",
                        "lat": 43.8563,
                        "lon": 18.4131,
                        "type": "war_trigger",
                        "summary": "war alliance cascade",
                        "tags": ["war", "kinetic_risk"],
                    },
                    {
                        "id": "evt_b",
                        "date": "1945-08-06",
                        "title": "Hiroshima nuclear threshold",
                        "location": "Hiroshima",
                        "lat": 34.3853,
                        "lon": 132.4553,
                        "type": "nuclear_threshold",
                        "summary": "nuclear war threshold",
                        "tags": ["war", "nuclear", "kinetic_risk"],
                    },
                ],
                "links": [{"source": "evt_a", "target": "evt_b", "kind": "war_threshold", "weight": 0.8}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cau = root / "causal_db"
    cau.mkdir(parents=True, exist_ok=True)
    (cau / "CAU-900_TEST.md").write_text("war nuclear attack treaty", encoding="utf-8")


def test_load_geo_events_returns_real_coordinates(tmp_path):
    _write_world_fixture(tmp_path)

    payload = load_geo_events(tmp_path)

    assert payload["events"][0]["lat"] == 43.8563
    assert payload["events"][1]["lon"] == 132.4553
    assert payload["links"][0]["kind"] == "war_threshold"


def test_news_geo_events_extract_declared_and_gazetteer_coordinates():
    news = [
        {"url": "https://reuters.com/a", "title": "Kyiv missile attack", "text": "war"},
        {"url": "https://apnews.com/b", "title": "Declared", "lat": 35.6892, "lon": 51.389, "location": "Tehran"},
    ]
    evidence = [{"weight": 0.85, "signals": {"kinetic_risk": 2}}, {"weight": 0.85, "signals": {}}]

    events = extract_news_geo_events(news, evidence)

    assert len(events) == 2
    assert events[0]["location"] == "Kyiv, Ukraine"
    assert events[1]["location"] == "Tehran"


def test_build_geo_timeline_adds_projection_and_correction(tmp_path):
    _write_world_fixture(tmp_path)
    news = [
        {"url": "https://reuters.com/a", "title": "Kyiv missile attack", "text": "missile attack war casualties", "date": "2026-01-01"},
        {"url": "https://apnews.com/b", "title": "Kursk troop movement", "text": "military troop conflict", "date": "2026-01-02"},
        {"url": "https://rt.com/c", "title": "Tehran strike warning", "text": "strike nuclear warning", "date": "2026-01-03"},
    ]

    result = build_geo_timeline(input_text="war", data_dir=tmp_path, news_sources=news)

    assert result["schema_version"] == "world_geotimeline.v1"
    assert result["news_filter"]["coordinate_count"] >= 2
    assert result["forecast_correction"]["correction_strength"] == "strong"
    assert any(event["projected"] for event in result["events"])
    assert any(link["kind"] == "forecast_projection_source" for link in result["links"])
    assert result["forecast_correction"]["scenario_deltas"]
    assert result["map_projection"] == "EPSG:3857_web_mercator"
    assert result["graph"]["layer_counts"]["projected"] == 1
    assert result["temporal_bounds"]["observed_end"] == "2026-01-03"
    assert all("distance_km" in link and "explanation" in link for link in result["links"])
    assert all(not event["date"].startswith("future:") for event in result["events"])


def test_revision_ledger_preserves_news_corrections(tmp_path):
    _write_world_fixture(tmp_path)
    payload = build_geo_timeline(
        input_text="war",
        data_dir=tmp_path,
        news_sources=[
            {"url": "https://reuters.com/a", "title": "Kyiv attack", "text": "war attack"},
            {"url": "https://apnews.com/b", "title": "Kursk conflict", "text": "war conflict"},
            {"url": "https://bbc.com/c", "title": "Tehran warning", "text": "nuclear warning"},
        ],
    )
    ledger = tmp_path / "runtime" / "world_revisions.jsonl"

    revision = append_revision(payload, path=ledger)
    revisions = load_revisions(query="war", path=ledger)

    assert revision["revision_id"].startswith("wrev_")
    assert len(revisions) == 1
    assert revisions[0]["news_summary"]["source_count"] == 3
    assert revisions[0]["graph_summary"]["event_count"] == len(payload["events"])
