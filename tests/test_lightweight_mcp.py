from __future__ import annotations

import json
import threading
import urllib.request
from io import BytesIO
from pathlib import Path

from kingdee_mcp.auth import hash_bearer_token
from kingdee_mcp.config import ServiceConfig, TransportConfig
from kingdee_mcp.mcp_lite import (
    KingdeeLiteApplication,
    _read_stdio_message,
    _write_stdio_message,
    create_http_server,
    process_http_request,
)


class FakeKingdeeClient:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.posts: list[tuple[str, dict, str]] = []
        self.views: list[tuple[str, str, str]] = []
        self.metadata_calls: list[tuple[str, str]] = []

    async def ensure_session(self, context):
        self.sessions.append(context.kingdee_username)
        return "fake-session"

    def query_payload(self, form_id, field_keys, filter_string="", order_string="FID DESC", start_row=0, limit=20):
        return {
            "FormId": form_id,
            "FieldKeys": field_keys,
            "FilterString": filter_string,
            "OrderString": order_string,
            "StartRow": start_row,
            "Limit": limit,
        }

    async def post(self, ep_key, payload, context):
        self.posts.append((ep_key, payload, context.kingdee_username))
        return [["row-1"]]

    async def view(self, form_id, bill_id, context):
        self.views.append((form_id, bill_id, context.kingdee_username))
        return {"Result": {"Result": {"FID": bill_id, "FBillNo": "B001", "FDocumentStatus": "B"}}}

    async def metadata(self, form_id, context):
        self.metadata_calls.append((form_id, context.kingdee_username))
        return {"Result": {"NeedReturnData": {"Entrys": []}}}


def service_config() -> ServiceConfig:
    return ServiceConfig(
        server_url="https://kingdee.example/k3cloud/",
        acct_id="acct",
        app_id="app",
        app_secret="secret",
        lcid=2052,
        default_username="local-user",
    )


def transport_config(token_config: str = "", *, auth_disabled: bool = False, port: int = 0) -> TransportConfig:
    return TransportConfig(
        transport="streamable-http",
        host="127.0.0.1",
        port=port,
        path="/mcp",
        token_config=token_config,
        auth_disabled=auth_disabled,
        issuer_url="http://127.0.0.1/mcp",
        resource_server_url="http://127.0.0.1/mcp",
        json_response=False,
        stateless_http=False,
        cors_allow_origins=("*",),
    )


def write_token_config(path: Path, token: str = "valid-token", *, enabled: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "tokens": {
                    hash_bearer_token(token): {
                        "operator": "alice",
                        "kingdee_username": "kingdee-alice",
                        "enabled": enabled,
                        "allowed_tools": ["read"],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def make_app(tmp_path: Path, *, auth_disabled: bool = False, enabled: bool = True) -> tuple[KingdeeLiteApplication, FakeKingdeeClient, str]:
    token_path = tmp_path / "tokens.json"
    write_token_config(token_path, enabled=enabled)
    fake = FakeKingdeeClient()
    app = KingdeeLiteApplication(
        service_config=service_config(),
        transport_config=transport_config(str(token_path), auth_disabled=auth_disabled),
        client=fake,  # type: ignore[arg-type]
    )
    return app, fake, "valid-token"


def post_http(url: str, token: str, payload: dict) -> tuple[object, object]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response, json.loads(response.read().decode("utf-8"))


def test_http_initialize_and_tools_list_are_plain_json(tmp_path: Path):
    app, _fake, token = make_app(tmp_path)
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/mcp"
        response, body = post_http(url, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers.get("mcp-session-id") is None
        assert body["result"]["serverInfo"]["name"] == "kingdee-mcp-lite"

        response, body = post_http(url, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert response.headers["content-type"].startswith("application/json")
        tools = body["result"]["tools"]
        assert len(tools) == 14
        assert {tool["name"] for tool in tools} == set(app.tools)
    finally:
        server.shutdown()
        server.server_close()
        app.close()


def test_valid_token_maps_to_kingdee_user_for_tool_call(tmp_path: Path):
    app, fake, token = make_app(tmp_path)
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kingdee_smoke_test", "arguments": {"run_query": False}}}
            ).encode("utf-8"),
        )
        assert status == 200
        result = body["result"]
        assert result["isError"] is False
        assert result["structuredContent"]["kingdee_username"] == "kingdee-alice"
        assert fake.sessions == ["kingdee-alice"]
    finally:
        app.close()


def test_invalid_or_disabled_token_rejected_before_tool_logic(tmp_path: Path):
    app, fake, _token = make_app(tmp_path, enabled=False)
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": "Bearer valid-token"},
            body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"),
        )
        assert status == 401
        assert body["error"] == "missing_or_invalid_bearer"
        assert fake.sessions == []
    finally:
        app.close()


def test_write_tool_not_registered_and_does_not_call_kingdee(tmp_path: Path):
    app, fake, token = make_app(tmp_path)
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "kingdee_save_bill", "arguments": {}}}
            ).encode("utf-8"),
        )
        assert status == 200
        assert body["result"]["isError"] is True
        assert body["result"]["structuredContent"]["error"]["type"] == "unknown_tool"
        assert fake.sessions == []
        assert fake.posts == []
    finally:
        app.close()


def test_options_preflight_does_not_require_bearer_and_allows_access_headers(tmp_path: Path):
    app, _fake, _token = make_app(tmp_path)
    try:
        server = create_http_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/mcp"
            req = urllib.request.Request(
                url,
                headers={
                    "Origin": "https://client.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type,cf-access-client-id,cf-access-client-secret",
                },
                method="OPTIONS",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                assert response.status == 204
                assert response.headers["Access-Control-Allow-Origin"] == "*"
                allow_headers = response.headers["Access-Control-Allow-Headers"].lower()
                assert "authorization" in allow_headers
                assert "cf-access-client-id" in allow_headers
                assert "cf-access-client-secret" in allow_headers
        finally:
            server.shutdown()
            server.server_close()
    finally:
        app.close()


def test_post_response_includes_cors_headers_when_origin_present(tmp_path: Path):
    app, _fake, token = make_app(tmp_path)
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/mcp"
        req = urllib.request.Request(
            url,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://client.example",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            assert response.status == 200
            assert response.headers["Access-Control-Allow-Origin"] == "*"
            assert response.headers["Content-Type"].startswith("application/json")
    finally:
        server.shutdown()
        server.server_close()
        app.close()




def test_http_server_handles_100_concurrent_tools_list(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    app, _fake, token = make_app(tmp_path)
    server = create_http_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/mcp"

        def one_call(index: int) -> int:
            _response, body = post_http(url, token, {"jsonrpc": "2.0", "id": index, "method": "tools/list", "params": {}})
            return len(body["result"]["tools"])

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = [future.result() for future in as_completed(executor.submit(one_call, i) for i in range(100))]
        assert results == [14] * 100
    finally:
        server.shutdown()
        server.server_close()
        app.close()


def test_stdio_content_length_framing_round_trip():
    stream = BytesIO()
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    _write_stdio_message(stream, payload)
    stream.seek(0)
    assert _read_stdio_message(stream) == payload
