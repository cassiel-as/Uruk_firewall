from services.world_simulator import build_world_state, should_trigger_world, simulate_world


def test_world_trigger_handles_explicit_and_abstract_queries():
    explicit = should_trigger_world("/world freedom and blackbox cost")
    abstract = should_trigger_world("freedom under formatting pressure")
    ordinary = should_trigger_world("hello")

    assert explicit["should_trigger"] is True
    assert explicit["explicit"] is True
    assert explicit["intercept_chat"] is True
    assert abstract["should_trigger"] is True
    assert abstract["intercept_chat"] is False
    assert "freedom" in abstract["terms"]
    assert ordinary["should_trigger"] is False


def test_build_world_state_has_core_entities(tmp_path):
    state = build_world_state(
        input_text="freedom, blackbox, cost",
        data_dir=tmp_path,
        tool_names=["read_file", "claim_origin_detector"],
    )

    entity_ids = {entity["id"] for entity in state["entities"]}
    assert state["schema_version"] == "world_state.v1"
    assert {"operator", "vessel", "kairos_active", "tool_registry", "current_query"} <= entity_ids
    assert state["relations"]
    assert state["forces"]
    assert state["source_counts"]["tools"] == 2


def test_simulation_returns_scenarios_and_evaluation(tmp_path):
    result = simulate_world(
        input_text="freedom and blackbox cost should be opened",
        data_dir=tmp_path,
        tool_names=["read_file", "claim_origin_detector"],
    )

    scenario_ids = {scenario["id"] for scenario in result["scenarios"]}
    assert result["ok"] is True
    assert result["schema_version"] == "world_simulation.v1"
    assert {"maintain_coordinate", "accept_external_frame", "open_blackbox"} <= scenario_ids
    assert result["evaluation"]["needs_world_view"] is True
    assert result["evaluation"]["recommended_scenario"] in scenario_ids
