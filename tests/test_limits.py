import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError

import pytest

from kingdee_mcp.mcp_lite import AsyncLoopRunner
from tests.test_lightweight_mcp import make_app


def test_tool_call_returns_server_busy_when_tool_slots_are_full(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_MAX_CONCURRENT_TOOLS", "1")
    monkeypatch.setenv("MCP_TOOL_QUEUE_TIMEOUT_SECONDS", "0.01")
    app, _fake, token = make_app(tmp_path)
    context = app.context_from_headers({"Authorization": f"Bearer {token}"})

    assert app._tool_semaphore.acquire(timeout=0.01)
    try:
        result = app.call_tool("kingdee_smoke_test", {"run_query": False}, context)
    finally:
        app._tool_semaphore.release()
        app.close()

    assert result["isError"] is True
    assert result["structuredContent"]["error"]["type"] == "server_busy"


def test_async_loop_runner_cancels_timed_out_coroutine():
    runner = AsyncLoopRunner()
    started = threading.Event()
    cancelled = threading.Event()

    async def slow_handler():
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    try:
        with pytest.raises(FutureTimeoutError):
            runner.run(slow_handler(), timeout=0.01)
        assert started.wait(timeout=1)
        assert cancelled.wait(timeout=1)
    finally:
        runner.close()


def test_material_image_call_returns_server_busy_when_image_slot_is_full(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_MAX_CONCURRENT_MATERIAL_IMAGE_TRANSFERS", "1")
    monkeypatch.setenv("MCP_MATERIAL_IMAGE_QUEUE_TIMEOUT_SECONDS", "0.01")
    app, _fake, token = make_app(tmp_path, allowed_tools=["write"])
    context = app.context_from_headers({"Authorization": f"Bearer {token}"})

    assert app._material_image_semaphore.acquire(timeout=0.01)
    try:
        result = app.call_tool(
            "kingdee_material_image",
            {
                "action": "download",
                "material_id": 13007761,
            },
            context,
        )
    finally:
        app._material_image_semaphore.release()
        app.close()
