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
