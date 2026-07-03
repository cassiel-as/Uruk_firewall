import asyncio

import pytest

from adapters import BaseAdapter
from services.inference_governor import (
    InferenceBudgetExceeded,
    begin_inference_session,
    execute_model_call,
    inference_snapshot,
    plan_inference_policy,
    reset_inference_session,
)


def test_policy_gives_full_pipeline_bounded_retry_headroom():
    policy = plan_inference_policy(
        preference="auto",
        route_kind="deep_reasoning",
        pipeline_mode="auto",
        estimated_calls=8,
    )

    assert policy.planned_calls == 8
    assert policy.hard_max_calls == 12


def test_economy_policy_removes_retry_headroom_not_required_stages():
    policy = plan_inference_policy(
        preference="economy",
        route_kind="deep_reasoning",
        pipeline_mode="trinity_only",
        estimated_calls=4,
    )

    assert policy.planned_calls == 4
    assert policy.hard_max_calls == 4


def test_protocol_compact_plans_two_calls_with_bounded_failover_headroom():
    policy = plan_inference_policy(
        preference="auto",
        route_kind="deep_reasoning",
        pipeline_mode="protocol_compact",
        estimated_calls=2,
    )

    assert policy.planned_calls == 2
    assert policy.hard_max_calls == 4


def test_actual_calls_are_counted_and_hard_cap_is_enforced():
    policy = plan_inference_policy(
        preference="economy",
        route_kind="small_task",
        pipeline_mode="plain_llm",
        estimated_calls=1,
    )
    token = begin_inference_session(policy)
    try:
        assert asyncio.run(execute_model_call(lambda: _answer("ok"), provider="ollama", model="tiny")) == "ok"
        with pytest.raises(InferenceBudgetExceeded):
            asyncio.run(execute_model_call(lambda: _answer("blocked"), provider="ollama", model="tiny"))
        usage = inference_snapshot()
    finally:
        reset_inference_session(token)

    assert usage["actual_requests"] == 1
    assert usage["successful_requests"] == 1
    assert usage["blocked_requests"] == 1
    assert usage["unique_model_count"] == 1
    assert usage["channels"]["local"] == 1


async def _answer(value):
    return value


class _TrackedAdapter(BaseAdapter):
    async def call(self, messages, model, temperature=0.7, max_tokens=4096):
        return "adapter-ok"


def test_adapter_calls_are_automatically_counted():
    policy = plan_inference_policy(
        preference="balanced",
        route_kind="small_task",
        pipeline_mode="plain_llm",
        estimated_calls=1,
    )
    token = begin_inference_session(policy)
    try:
        adapter = _TrackedAdapter()
        assert asyncio.run(adapter.call([], "unit-model")) == "adapter-ok"
        usage = inference_snapshot()
    finally:
        reset_inference_session(token)

    assert usage["actual_requests"] == 1
    assert usage["calls"][0]["model"] == "unit-model"
    assert usage["calls"][0]["status"] == "success"
