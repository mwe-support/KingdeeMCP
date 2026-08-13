from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from kingdee_mcp.access_log import (
    AccessLogConfig,
    JsonAccessLogger,
    load_access_log_config,
)
from kingdee_mcp.mcp_lite import create_http_server
from tests.test_lightweight_mcp import make_app


def test_structured_access_log_records_tool_call_and_request_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "logs" / "access.jsonl"
    monkeypatch.setenv("MCP_ACCESS_LOG_PATH", str(log_path))
    monkeypatch.setenv("MCP_ACCESS_LOG_RETENTION_DAYS", "30")
    app, _fake, token = make_app(tmp_path)
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    response_body = b""
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/mcp",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_smoke_test",
                        "arguments": {"run_query": False},
                    },
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Request-ID": "workbuddy-test-123",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read()
            assert response.headers["X-Request-ID"] == "workbuddy-test-123"
    finally:
        server.shutdown()
        server.server_close()
        app.close()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event"] == "mcp_access"
    assert event["request_id"] == "workbuddy-test-123"
    assert event["user"] == "alice"
    assert event["kingdee_username"] == "kingdee-alice"
    assert event["role"] == "read"
    assert event["tool_name"] == "kingdee_smoke_test"
    assert event["mcp_method"] == "tools/call"
    assert event["duration_ms"] >= 0
    assert event["response_bytes"] == len(response_body)
    assert event["status"] == "success"
    assert event["http_status"] == 200
    assert event["error_type"] is None
    assert "valid-token" not in lines[0]
    assert "Authorization" not in lines[0]


def test_invalid_request_id_is_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "access.jsonl"
    monkeypatch.setenv("MCP_ACCESS_LOG_PATH", str(log_path))
    app, _fake, token = make_app(tmp_path)
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "X-Request-ID": "invalid id!"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            request_id = response.headers["X-Request-ID"]
            response.read()
        assert request_id != "invalid id!"
        assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    finally:
        server.shutdown()
        server.server_close()
        app.close()
    assert not log_path.exists()


def test_access_log_prunes_files_older_than_retention(tmp_path: Path) -> None:
    log_path = tmp_path / "access.jsonl"
    expired = tmp_path / "access.jsonl.2026-01-01"
    expired.write_text("{}\n", encoding="utf-8")
    old = time.time() - 31 * 86400
    os.utime(expired, (old, old))

    logger = JsonAccessLogger(AccessLogConfig(str(log_path), retention_days=30))
    logger.close()
    assert not expired.exists()


def test_access_log_retention_cannot_exceed_30_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ACCESS_LOG_PATH", "/tmp/access.jsonl")
    monkeypatch.setenv("MCP_ACCESS_LOG_RETENTION_DAYS", "31")
    with pytest.raises(ValueError, match="between 1 and 30"):
        load_access_log_config()
