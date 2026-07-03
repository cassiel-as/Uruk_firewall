import asyncio
import time

from services.provider_rate_limiter import ProviderRateLimiter


def test_concurrent_calls_are_serialized_by_provider_interval():
    limiter = ProviderRateLimiter({"test-provider": 0.03})

    async def reserve_twice():
        started = time.monotonic()
        first, second = await asyncio.gather(
            limiter.wait_for_slot("test-provider"),
            limiter.wait_for_slot("test-provider"),
        )
        return first, second, time.monotonic() - started

    first, second, elapsed = asyncio.run(reserve_twice())

    assert first["allowed"] is True
    assert second["allowed"] is True
    assert max(first["waited_seconds"], second["waited_seconds"]) >= 0.025
    assert elapsed >= 0.025


def test_rate_limit_blocks_reserved_call_before_network_request():
    limiter = ProviderRateLimiter({"test-provider": 0.03})

    async def block_while_second_waits():
        await limiter.wait_for_slot("test-provider")
        pending = asyncio.create_task(limiter.wait_for_slot("test-provider"))
        await asyncio.sleep(0.005)
        limiter.record_rate_limit("test-provider", retry_after_seconds=1.0)
        return await pending

    result = asyncio.run(block_while_second_waits())

    assert result["allowed"] is False
    assert result["retry_after_seconds"] > 0
    snapshot = limiter.snapshot()["test-provider"]
    assert snapshot["blocked"] is True
    assert snapshot["rate_limits"] == 1
