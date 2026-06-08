import httpx
import pytest

from kingdee_mcp.auth import OperatorContext
from kingdee_mcp.config import ServiceConfig
from kingdee_mcp.kingdee_client import KingdeeWebAPIClient


def response(status_code: int, text: str) -> httpx.Response:
    return httpx.Response(status_code, content=text.encode("utf-8"), request=httpx.Request("POST", "https://example.com"))


def test_detects_kingdee_chinese_session_lost_response():
    resp = response(200, '{"Result":{"ResponseStatus":{"IsSuccess":false,"Errors":[{"Message":"会话信息已丢失，请重新登录"}]}}}')

    assert KingdeeWebAPIClient.is_session_expired_response(resp) is True


def test_detects_english_session_lost_response_and_401():
    assert KingdeeWebAPIClient.is_session_expired_response(response(401, "")) is True
    assert KingdeeWebAPIClient.is_session_expired_response(response(200, "Invalid session, please login again")) is True


def test_non_session_business_response_is_not_expired():
    assert KingdeeWebAPIClient.is_session_expired_response(response(200, '[["row-1"]]')) is False
    assert KingdeeWebAPIClient.is_session_expired_response(response(500, "internal error")) is False


class FakeSessionManager:
    async def get_session(self, kingdee_username):
        return "session-id"

    async def refresh_session(self, kingdee_username):
        return "session-id-refreshed"

    async def get_cookie_header(self, kingdee_username):
        return "kdservice-sessionid=session-id; ASP.NET_SessionId=asp-id"

    async def refresh_cookie_header(self, kingdee_username):
        return "kdservice-sessionid=session-id-refreshed; ASP.NET_SessionId=asp-id-refreshed"


class FakeAsyncClient:
    requests = []
    responses = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


def service_config() -> ServiceConfig:
    return ServiceConfig(
        server_url="https://example.com/k3cloud/",
        acct_id="acct",
        app_id="app",
        app_secret="secret",
        lcid=2052,
    )


def operator_context() -> OperatorContext:
    return OperatorContext(operator="alice", kingdee_username="kingdee-alice", allowed_tools=frozenset({"read"}))


@pytest.mark.asyncio
async def test_post_sends_full_cookie_header_and_refreshes_with_full_cookie(monkeypatch):
    import kingdee_mcp.kingdee_client as client_module

    FakeAsyncClient.requests = []
    FakeAsyncClient.responses = [
        response(200, '{"Result":{"ResponseStatus":{"IsSuccess":false,"Errors":[{"Message":"会话信息已丢失，请重新登录"}]}}}'),
        response(200, '[["row-1"]]'),
    ]
    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeAsyncClient)
    client = KingdeeWebAPIClient(service_config())
    client._session_manager = FakeSessionManager()

    result = await client.post("query", {"FormId": "SAL_SaleOrder", "FieldKeys": "FID"}, operator_context())

    assert result == [["row-1"]]
    assert [request[1]["headers"]["Cookie"] for request in FakeAsyncClient.requests] == [
        "kdservice-sessionid=session-id; ASP.NET_SessionId=asp-id",
        "kdservice-sessionid=session-id-refreshed; ASP.NET_SessionId=asp-id-refreshed",
    ]
