from __future__ import annotations

import json
import threading
import urllib.request
from io import BytesIO
from pathlib import Path

from kingdee_mcp.auth import hash_bearer_token
from kingdee_mcp.config import ServiceConfig, TransportConfig
from kingdee_mcp.light_tools import CORE_READ_TOOL_NAMES, map_query_rows
from kingdee_mcp.mcp_lite import (
    KingdeeLiteApplication,
    _read_stdio_message,
    _write_stdio_message,
    create_http_server,
    process_http_request,
)
from kingdee_mcp.token_cli import save_token_config


class FakeKingdeeClient:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.posts: list[tuple[str, dict, str]] = []
        self.raw_calls: list[tuple[str, str, dict, str]] = []
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
        if payload.get("FormId") == "GL_BALANCE":
            return [["001", 2026, 6, "1001", "库存现金", "PRE001", "人民币", 11337.0, 0.0, 0.0, 87100.0, 89054.0, 11337.0, 0]]
        if payload.get("FormId") == "GL_VOUCHER":
            return [
                ["V001", "2026-06-09T00:00:00", "付", "97", "测试付款", "1001", "库存现金", "PRE001", "人民币", 0.0, 300.0, "-1", "C", "过账员", 1001],
                ["V002", "2026-06-12T00:00:00", "付", "98", "测试收款", "1001", "库存现金", "PRE001", "人民币", 500.0, 0.0, "1", "C", "过账员", 1002],
                ["V003", "2026-06-13T00:00:00", "付", "99", "测试收款", "1001", "库存现金", "PRE001", "人民币", 100.0, 0.0, "1", "C", "过账员", 1003],
            ]
        return [["row-1"]]

    async def raw(self, ep_key, form_id, data_obj, context):
        self.raw_calls.append((ep_key, form_id, data_obj, context.kingdee_username))
        return {"Result": {"ResponseStatus": {"IsSuccess": True}, "FID": "100001", "FBillNo": "B001"}}

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


def write_token_config(
    path: Path,
    token: str = "valid-token",
    *,
    enabled: bool = True,
    operator: str = "alice",
    kingdee_username: str = "kingdee-alice",
    allowed_tools: list[str] | None = None,
) -> None:
    save_token_config(
        path,
        {
            "tokens": {
                hash_bearer_token(token): {
                    "operator": operator,
                    "kingdee_username": kingdee_username,
                    "enabled": enabled,
                    "allowed_tools": allowed_tools or ["read"],
                }
            }
        },
    )


def make_app(tmp_path: Path, *, auth_disabled: bool = False, enabled: bool = True, allowed_tools: list[str] | None = None) -> tuple[KingdeeLiteApplication, FakeKingdeeClient, str]:
    token_path = tmp_path / "tokens.json"
    write_token_config(token_path, enabled=enabled, allowed_tools=allowed_tools)
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
        assert {tool["name"] for tool in tools} == CORE_READ_TOOL_NAMES
    finally:
        server.shutdown()
        server.server_close()
        app.close()


def test_core_tool_descriptions_do_not_contain_mojibake(tmp_path: Path):
    app, _fake, token = make_app(tmp_path)
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"),
        )
        assert status == 200
        payload = json.dumps(body, ensure_ascii=False)
        assert "??" not in payload
        assert "采购订单" in payload
        assert "即时库存" in payload
    finally:
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


def test_subledger_combines_balance_and_voucher_webapi_data(tmp_path: Path):
    app, fake, token = make_app(
        tmp_path,
        allowed_tools=["kingdee_query_subledger"],
    )
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_query_subledger",
                        "arguments": {
                            "start_year": 2026,
                            "start_period": 6,
                            "end_year": 2026,
                            "end_period": 6,
                            "account_book_number": "001",
                            "start_account_number": "1001",
                            "end_account_number": "1001",
                            "currency_number": "PRE001",
                            "exclude_adjustment_vouchers": True,
                            "limit": 2,
                        },
                    },
                }
            ).encode("utf-8"),
        )

        assert status == 200
        result = body["result"]["structuredContent"]
        assert result["report_form_id"] == "GL_RPT_SubLedger"
        assert result["report_name"] == "明细分类账"
        assert result["data_sources"] == ["GL_BALANCE", "GL_VOUCHER"]
        assert result["count"] == 2
        assert result["has_more"] is True
        assert result["opening_balances"] == [
            {
                "account_book_number": "001",
                "year": 2026,
                "period": 6,
                "account_number": "1001",
                "account_name": "库存现金",
                "currency_number": "PRE001",
                "currency_name": "人民币",
                "begin_balance": 11337.0,
                "debit": 0.0,
                "credit": 0.0,
                "ytd_debit": 87100.0,
                "ytd_credit": 89054.0,
                "end_balance": 11337.0,
                "adjust_period": 0,
            }
        ]
        assert result["opening_balances_has_more"] is False
        assert result["closing_balances"] == result["opening_balances"]
        assert result["closing_balances_has_more"] is False
        assert result["entries"][0]["voucher_number"] == "V001"
        assert result["entries"][0]["credit"] == 300.0

        assert len(fake.posts) == 2
        balance_call = fake.posts[0]
        voucher_call = fake.posts[1]
        assert balance_call[0] == "query"
        assert balance_call[1]["FormId"] == "GL_BALANCE"
        assert "FACCOUNTBOOKID.FNumber = '001'" in balance_call[1]["FilterString"]
        assert "FAccountID.FNumber >= '1001'" in balance_call[1]["FilterString"]
        assert "FCurrencyID.FNumber = 'PRE001'" in balance_call[1]["FilterString"]
        assert "FAdjustPeriod = 0" in balance_call[1]["FilterString"]
        assert balance_call[2] == "kingdee-alice"
        assert voucher_call[0] == "query"
        assert voucher_call[1]["FormId"] == "GL_VOUCHER"
        assert "FPOSTERID > 0" in voucher_call[1]["FilterString"]
        assert "FInvalid = '0'" in voucher_call[1]["FilterString"]
        assert "FISADJUSTVOUCHER = 0" in voucher_call[1]["FilterString"]
        assert voucher_call[1]["StartRow"] == 0
        assert voucher_call[1]["Limit"] == 3
        assert voucher_call[1]["OrderString"].endswith("FEntity_FEntryID ASC")
        assert voucher_call[2] == "kingdee-alice"
        assert fake.raw_calls == []
    finally:
        app.close()


def test_subledger_requires_account_book_number_before_kingdee_call(tmp_path: Path):
    app, fake, token = make_app(
        tmp_path,
        allowed_tools=["kingdee_query_subledger"],
    )
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_query_subledger",
                        "arguments": {
                            "start_year": 2026,
                            "end_year": 2026,
                        },
                    },
                }
            ).encode("utf-8"),
        )

        assert status == 200
        result = body["result"]
        assert result["isError"] is True
        assert result["structuredContent"]["error"]["type"] == "invalid_arguments"
        assert "account_book_number" in result["structuredContent"]["error"]["message"]
        assert fake.raw_calls == []
    finally:
        app.close()


def test_subledger_escapes_filter_values_and_can_include_unposted(tmp_path: Path):
    app, fake, token = make_app(
        tmp_path,
        allowed_tools=["kingdee_query_subledger"],
    )
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_query_subledger",
                        "arguments": {
                            "start_year": 2026,
                            "end_year": 2026,
                            "account_book_number": "00'1",
                            "start_account_number": "10'01",
                            "exclude_adjustment_vouchers": False,
                            "include_unposted_vouchers": True,
                        },
                    },
                }
            ).encode("utf-8"),
        )

        assert status == 200
        result = body["result"]
        assert result["isError"] is False
        filters = [call[1]["FilterString"] for call in fake.posts]
        assert all("00''1" in item for item in filters)
        assert all("10''01" in item for item in filters)
        assert "FAdjustPeriod = 0" not in fake.posts[0][1]["FilterString"]
        voucher_filter = fake.posts[-1][1]["FilterString"]
        assert "FISADJUSTVOUCHER = 0" not in voucher_filter
        assert "FPOSTERID > 0" not in voucher_filter
        assert "FInvalid = '0'" in voucher_filter
        assert fake.raw_calls == []
    finally:
        app.close()


def test_subledger_queries_both_boundary_balances_for_multi_period(tmp_path: Path):
    app, fake, token = make_app(
        tmp_path,
        allowed_tools=["kingdee_query_subledger"],
    )
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_query_subledger",
                        "arguments": {
                            "start_year": 2026,
                            "start_period": 5,
                            "end_year": 2026,
                            "end_period": 6,
                            "account_book_number": "001",
                            "start_account_number": "1001",
                        },
                    },
                }
            ).encode("utf-8"),
        )

        assert status == 200
        assert body["result"]["isError"] is False
        assert [call[1]["FormId"] for call in fake.posts] == ["GL_BALANCE", "GL_BALANCE", "GL_VOUCHER"]
        assert "FPeriod = 5" in fake.posts[0][1]["FilterString"]
        assert "FPeriod = 6" in fake.posts[1][1]["FilterString"]
    finally:
        app.close()


def test_subledger_caps_limit_at_100(tmp_path: Path):
    app, fake, token = make_app(
        tmp_path,
        allowed_tools=["kingdee_query_subledger"],
    )
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_query_subledger",
                        "arguments": {
                            "start_year": 2026,
                            "end_year": 2026,
                            "account_book_number": "001",
                            "start_account_number": "1001",
                            "limit": 101,
                        },
                    },
                }
            ).encode("utf-8"),
        )

        assert status == 200
        result = body["result"]
        assert result["isError"] is True
        assert result["structuredContent"]["error"]["type"] == "invalid_arguments"
        assert "limit must be <= 100" in result["structuredContent"]["error"]["message"]
        assert fake.raw_calls == []
    finally:
        app.close()


def test_subledger_balance_pagination_uses_limit_plus_one(tmp_path: Path):
    app, fake, token = make_app(
        tmp_path,
        allowed_tools=["kingdee_query_subledger"],
    )
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_query_subledger",
                        "arguments": {
                            "start_year": 2026,
                            "end_year": 2026,
                            "account_book_number": "001",
                            "start_account_number": "1001",
                            "balance_start_row": 25,
                            "balance_limit": 40,
                        },
                    },
                }
            ).encode("utf-8"),
        )

        assert status == 200
        assert body["result"]["isError"] is False
        assert fake.posts[0][1]["StartRow"] == 25
        assert fake.posts[0][1]["Limit"] == 41
        result = body["result"]["structuredContent"]
        assert result["balance_start_row"] == 25
        assert result["balance_limit"] == 40
    finally:
        app.close()


def test_map_query_rows_surfaces_execute_bill_query_business_error():
    try:
        map_query_rows(
            [
                [
                    {
                        "Result": {
                            "ResponseStatus": {
                                "IsSuccess": False,
                                "Errors": [{"Message": "字段权限不足"}],
                            }
                        }
                    }
                ]
            ],
            ("field",),
        )
    except RuntimeError as exc:
        assert "字段权限不足" in str(exc)
    else:
        raise AssertionError("ExecuteBillQuery business errors must be surfaced")


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


def test_token_config_hot_reloads_new_token_without_restart(tmp_path: Path):
    token_path = tmp_path / "tokens.json"
    write_token_config(token_path, token="old-token", kingdee_username="kingdee-old")
    fake = FakeKingdeeClient()
    app = KingdeeLiteApplication(
        service_config=service_config(),
        transport_config=transport_config(str(token_path)),
        client=fake,  # type: ignore[arg-type]
    )
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": "Bearer old-token"},
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "kingdee_smoke_test", "arguments": {"run_query": False}}}
            ).encode("utf-8"),
        )
        assert status == 200
        assert body["result"]["structuredContent"]["kingdee_username"] == "kingdee-old"

        write_token_config(token_path, token="new-token-for-hot-reload", kingdee_username="kingdee-new")

        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": "Bearer old-token"},
            body=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8"),
        )
        assert status == 401
        assert body["error"] == "missing_or_invalid_bearer"

        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": "Bearer new-token-for-hot-reload"},
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kingdee_smoke_test", "arguments": {"run_query": False}}}
            ).encode("utf-8"),
        )
        assert status == 200
        assert body["result"]["structuredContent"]["kingdee_username"] == "kingdee-new"
    finally:
        app.close()


def test_token_config_hot_reload_fails_closed_and_recovers(tmp_path: Path):
    token_path = tmp_path / "tokens.json"
    write_token_config(token_path, token="valid-token")
    fake = FakeKingdeeClient()
    app = KingdeeLiteApplication(
        service_config=service_config(),
        transport_config=transport_config(str(token_path)),
        client=fake,  # type: ignore[arg-type]
    )
    try:
        token_path.write_text("{not valid json", encoding="utf-8")

        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": "Bearer valid-token"},
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "kingdee_smoke_test", "arguments": {"run_query": False}}}
            ).encode("utf-8"),
        )
        assert status == 401
        assert body["error"] == "missing_or_invalid_bearer"
        assert fake.sessions == []

        write_token_config(token_path, token="recovered-token", kingdee_username="kingdee-recovered")

        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": "Bearer recovered-token"},
            body=json.dumps(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "kingdee_smoke_test", "arguments": {"run_query": False}}}
            ).encode("utf-8"),
        )
        assert status == 200
        assert body["result"]["structuredContent"]["kingdee_username"] == "kingdee-recovered"
    finally:
        app.close()


def test_write_tool_disallowed_for_read_token_and_does_not_call_kingdee(tmp_path: Path):
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
        assert body["result"]["structuredContent"]["error"]["type"] == "disallowed_tool"
        assert fake.sessions == []
        assert fake.posts == []
        assert fake.raw_calls == []
    finally:
        app.close()


def test_full_read_profile_lists_migrated_read_tools(tmp_path: Path):
    app, _fake, token = make_app(tmp_path, allowed_tools=["full-read"])
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}}).encode("utf-8"),
        )
        assert status == 200
        names = {tool["name"] for tool in body["result"]["tools"]}
        assert len(names) > 14
        assert "kingdee_query_production_orders" in names
        assert "kingdee_save_bill" not in names
        assert "kingdee_usage_stats" not in names
    finally:
        app.close()


def test_write_profile_can_call_migrated_save_tool(tmp_path: Path):
    app, fake, token = make_app(tmp_path, allowed_tools=["write"])
    try:
        status, body = process_http_request(
            app,
            method="POST",
            path="/mcp",
            headers={"Authorization": f"Bearer {token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "tools/call",
                    "params": {
                        "name": "kingdee_save_bill",
                        "arguments": {"form_id": "PUR_PurchaseOrder", "model": {"FBillTypeID": {"FNumber": "CGDD01_SYS"}}},
                    },
                }
            ).encode("utf-8"),
        )
        assert status == 200
        assert body["result"]["isError"] is False
        assert fake.raw_calls[0][0] == "save"
        assert fake.raw_calls[0][1] == "PUR_PurchaseOrder"
        assert isinstance(fake.raw_calls[0][2]["Model"], dict)
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


def test_image_tool_result_serializes_base64_only_once():
    from kingdee_mcp.mcp_lite import tool_result

    image_base64 = "aGVsbG8="
    result = tool_result(
        {
            "success": True,
            "mime_type": "image/png",
            "sha256": "example-sha256",
            "image_base64": image_base64,
        }
    )

    assert result["content"][1] == {"type": "image", "data": image_base64, "mimeType": "image/png"}
