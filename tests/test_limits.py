import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from kingdee_mcp import server


def test_limit_snapshot_includes_operational_defaults():
    snapshot = server._limit_snapshot()

    assert snapshot["max_concurrent_tools"] >= 1
    assert snapshot["max_concurrent_kingdee_requests"] >= 1
    assert snapshot["rate_limit_per_operator_per_minute"] >= 0


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_rejects_after_limit():
    limiter = server.SlidingWindowRateLimiter(limit=1, window_seconds=60)

    await limiter.check("operator-a", label="operator-a")
    with pytest.raises(ToolError, match="Rate limit exceeded"):
        await limiter.check("operator-a", label="operator-a")


@pytest.mark.asyncio
async def test_acquire_limited_slot_times_out_when_queue_is_full():
    semaphore = asyncio.Semaphore(0)

    with pytest.raises(ToolError, match="Server is busy"):
        async with server._acquire_limited_slot(semaphore, 0.01, "test slot"):
            pass
