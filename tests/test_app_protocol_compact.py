import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from failover import FailoverTrigger, HealthTracker


def _events(raw: str) -> list[tuple[str, dict]]:
    events = []
    current = None
    for line in raw.splitlines():
        if line.startswith("event: "):
            current = line[7:]
        elif line.startswith("data: ") and current:
            events.append((current, json.loads(line[6:])))
            current = None
    return events


def test_auto_protocol_question_uses_only_father_and_spirit(monkeypatch):
    calls = []

    async def fake_call_node(role, user_input, protocol_text="", extra_context="", **_kwargs):
        calls.append(role)
        if role == "spirit":
            return (
                "Audit complete.\n"
                "---SPIRIT_METADATA---\n"
                '{"trigger_mode":"SEMANTIC","semantic_score":2,'
                '"magnitude":5.5,"primary_assumption":"literal derivation"}\n'
                "---END_METADATA---"
            )
        return "LIE_COST is an operational protocol constant, not a Landauer derivation."

    monkeypatch.setattr(app_module.console, "call_node", fake_call_node)
    monkeypatch.setattr(
        app_module.console,
        "save_kairos",
        lambda *_args, **_kwargs: Path("protocol_compact_test.md"),
    )

    with TestClient(app_module.app) as client:
        response = client.post(
            "/api/stream",
            json={
                "input": "Landauer 係 bit erasure，唔係 deception，係嚴格推導定係比喻？",
                "pipeline_mode": "auto",
                "in_session_history": [
                    {
                        "turn_id": 1,
                        "timestamp": "2026-06-24T12:00:00",
                        "input": "FREEDOM_LOSS_ENTROPY 同 LIE_COST 有咩關係？",
                        "modes": {},
                    }
                ],
            },
        )

    assert response.status_code == 200
    events = _events(response.text)
    dispatch = next(data for name, data in events if name == "dispatch")
    budget = next(data for name, data in events if name == "inference_budget")
    decision = next(data for name, data in events if name == "council_decision")
    assert dispatch["mode"] == "protocol_compact"
    assert budget["policy"]["planned_calls"] == 2
    assert set(calls) == {"father", "spirit"}
    assert len(calls) == 2
    assert decision["verdict"] == "interrupt"


def test_health_reset_protects_active_rate_limit_cooldown(monkeypatch):
    tracker = HealthTracker(cooldown_seconds=30)
    tracker.record_failure(
        "cerebras_llama", FailoverTrigger.HTTP_429, "rate limited", cool_down=True,
    )
    monkeypatch.setattr(app_module.console, "health", tracker)

    with TestClient(app_module.app) as client:
        protected = client.post("/api/nodes/health/reset", json={})
        forced = client.post("/api/nodes/health/reset", json={"force": True})

    assert protected.status_code == 409
    assert protected.json()["detail"]["code"] == "rate_limit_cooldown_protected"
    assert forced.status_code == 200
    assert forced.json() == {"cleared": "all", "forced": True}


def test_ambiguous_date_stream_uses_scope_clarification():
    with TestClient(app_module.app) as client:
        response = client.post(
            "/api/stream",
            json={
                "input": "3月8號發生過咩？",
                "pipeline_mode": "auto",
            },
        )

    assert response.status_code == 200
    events = _events(response.text)
    dispatch = next(data for name, data in events if name == "dispatch")
    direct = next(data for name, data in events if name == "direct_response")
    assert dispatch["mode"] == "date_scope_clarification"
    assert direct["model"] == "date_scope_clarification"
    assert "Kairos" in direct["text"]
    assert "世界大事" in direct["text"]


def test_auto_self_upgrade_routes_to_codex_app_relay(monkeypatch):
    import services.app_controller as app_controller

    monkeypatch.setattr(
        app_controller,
        "list_apps",
        lambda: [
            {"key": "codex", "display": "Codex", "icon": "CX", "running": True},
        ],
    )

    async def fake_send_and_receive(app_key, text, **_kwargs):
        return {
            "ok": True,
            "response": f"handled by {app_key}: {text[:20]}",
            "method": "test",
        }

    monkeypatch.setattr(app_controller, "send_and_receive", fake_send_and_receive)
    monkeypatch.setattr(app_controller, "get_deps_status", lambda: {"is_windows": True})
    monkeypatch.setattr(app_module.console, "save_kairos", lambda *_args, **_kwargs: Path("self_upgrade_app_relay_test.md"))

    with TestClient(app_module.app) as client:
        response = client.post(
            "/api/stream",
            json={
                "input": "幫我分析而家系統最大瓶頸，並提出可執行升級方案。",
                "pipeline_mode": "auto",
            },
        )

    assert response.status_code == 200
    events = _events(response.text)
    dispatch = next(data for name, data in events if name == "dispatch")
    direct = next(data for name, data in events if name == "direct_response")
    assert dispatch["mode"] == "app_relay"
    assert dispatch["cost_metrics"]["route_kind"] == "self_upgrade"
    assert direct["provider"] == "app_relay/codex"


def test_auto_current_affairs_query_switches_to_news_browsernode(monkeypatch):
    async def fake_fetch_with_sources(query, min_sources=3, **_kwargs):
        return {
            "primary_sources": [
                {
                    "url": "https://www.reuters.com/markets/rates-a",
                    "title": "Fed rate decision",
                    "snippet": "Federal Reserve interest rate decision.",
                    "text": "Federal Reserve interest rate decision.",
                    "source_engine": "test",
                },
                {
                    "url": "https://apnews.com/article/fed-rates-b",
                    "title": "Federal Reserve",
                    "snippet": "Recent Federal Reserve decision.",
                    "text": "Recent Federal Reserve decision.",
                    "source_engine": "test",
                },
                {
                    "url": "https://www.bbc.com/news/business-c",
                    "title": "Markets and rates",
                    "snippet": "Markets react to central bank rates.",
                    "text": "Markets react to central bank rates.",
                    "source_engine": "test",
                },
            ],
            "raw_count": 3,
            "fetched_count": 3,
            "errors": [],
            "query": query,
            "engines_used": [{"engine": "test", "results_count": 3, "reason": "test"}],
            "coordinate_diversity": 3,
        }

    async def fake_delabeling(user_input):
        return {"delabeled_input": user_input, "abort_signal": "no"}

    async def fake_explanation(_stage1):
        return {
            "geography_analysis": "grounded",
            "religion_analysis": "grounded",
            "psychology_analysis": "grounded",
            "history_analysis": "grounded",
            "philosophy_dispatch": "grounded",
            "causal_summary": "grounded",
            "abort_signal": "no",
        }

    async def fake_filter(_stage1, _stage2):
        return {"abort_signal": "no", "law1_art": {"score": 0.0}}

    async def fake_dispatcher(_user_input):
        return {"mode": "firewall", "references": [], "suggested_data_refs": []}

    async def fake_call_node(role, *_args, **_kwargs):
        if role == "council":
            return "{}"
        return f"{role} output"

    monkeypatch.setattr(app_module.browser_node, "fetch_with_sources", fake_fetch_with_sources)
    monkeypatch.setattr(app_module.console, "call_delabeling", fake_delabeling)
    monkeypatch.setattr(app_module.console, "call_explanation", fake_explanation)
    monkeypatch.setattr(app_module.console, "call_filter", fake_filter)
    monkeypatch.setattr(app_module.console, "call_dispatcher", fake_dispatcher)
    monkeypatch.setattr(app_module.console, "call_node", fake_call_node)
    monkeypatch.setattr(
        app_module.console,
        "_parse_son_veto_metadata",
        lambda _text: {
            "veto_type": "none",
            "authentic_suffering_score": 0.0,
            "physical_cost_present": False,
            "primary_pain_locus": "",
        },
    )
    monkeypatch.setattr(app_module.console, "_downgrade_historical_third_person_veto", lambda meta, _query: meta)
    monkeypatch.setattr(app_module.console, "_should_father_pause", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        app_module.console,
        "_parse_spirit_metadata",
        lambda _text: {"trigger_mode": "NONE", "semantic_score": 0, "magnitude": 0.0, "primary_assumption": ""},
    )
    monkeypatch.setattr(app_module.console, "_apply_spirit_stochastic_gate", lambda meta, _query: meta)
    monkeypatch.setattr(app_module.console, "_should_rescan", lambda _meta: False)
    monkeypatch.setattr(app_module.console, "_parse_eight_law_scores", lambda _stage3: {})
    monkeypatch.setattr(app_module.console, "_detect_alignment_resonance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        app_module.console,
        "_parse_council_decision",
        lambda _text: {
            "verdict": "consensus",
            "reason": "test",
            "son_promoted": False,
            "father_dominated": False,
            "spirit_dominated": False,
            "consensus_weights": None,
            "primary_dimension": "",
        },
    )
    monkeypatch.setattr(app_module.console, "_fuse_voices", lambda *_args, **_kwargs: "grounded final")
    monkeypatch.setattr(app_module.console, "rag_block", lambda _query: "")
    monkeypatch.setattr(app_module.console, "save_kairos", lambda *_args, **_kwargs: Path("auto_news_test.md"))

    with TestClient(app_module.app) as client:
        response = client.post(
            "/api/stream",
            json={
                "input": "今日係 2026 年 6 月 25 日。美聯儲最近嘅利率決定對座標說點理解？",
                "pipeline_mode": "auto",
            },
        )

    assert response.status_code == 200
    events = _events(response.text)
    dispatch = next(data for name, data in events if name == "dispatch")
    budget = next(data for name, data in events if name == "inference_budget")
    assert dispatch["mode"] == "news"
    assert budget["policy"]["pipeline_mode"] == "news"
    assert any(name == "browser_audit_summary" for name, _data in events)
