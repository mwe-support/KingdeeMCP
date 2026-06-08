import pytest

from kingdee_mcp.config import ServiceConfig
from kingdee_mcp.kingdee_session import KingdeeSessionManager


class FakeCookie:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FakeCookies:
    def __init__(self, pairs):
        self.jar = [FakeCookie(name, value) for name, value in pairs]


class FakeResponse:
    def __init__(self, session_id, cookie_pairs=None):
        self._session_id = session_id
        self.cookies = FakeCookies(cookie_pairs or [])

    def raise_for_status(self):
        return None

    def json(self):
        return {"LoginResultType": 1, "KDSVCSessionId": self._session_id}


class FakeAsyncClient:
    calls = []
    cookie_pairs = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json, headers):
        username = json["parameters"][1]
        self.calls.append((url, username))
        session_id = f"session-{username}-{len(self.calls)}"
        pairs = [(name, value.format(username=username, index=len(self.calls), session_id=session_id)) for name, value in self.cookie_pairs]
        return FakeResponse(session_id, pairs)


@pytest.mark.asyncio
async def test_session_manager_caches_sessions_per_kingdee_user(monkeypatch):
    import kingdee_mcp.kingdee_session as session_module

    FakeAsyncClient.calls = []
    FakeAsyncClient.cookie_pairs = []
    monkeypatch.setattr(session_module.httpx, "AsyncClient", FakeAsyncClient)
    cfg = ServiceConfig(
        server_url="https://example.com/k3cloud/",
        acct_id="acct",
        app_id="app",
        app_secret="secret",
        lcid=2052,
    )
    manager = KingdeeSessionManager(cfg, lambda: "https://example.com/login")

    first_a = await manager.get_session("user_a")
    second_a = await manager.get_session("user_a")
    first_b = await manager.get_session("user_b")
    refreshed_a = await manager.refresh_session("user_a")

    assert first_a == second_a
    assert first_a == "session-user_a-1"
    assert first_b == "session-user_b-2"
    assert refreshed_a == "session-user_a-3"
    assert FakeAsyncClient.calls == [
        ("https://example.com/login", "user_a"),
        ("https://example.com/login", "user_b"),
        ("https://example.com/login", "user_a"),
    ]


@pytest.mark.asyncio
async def test_session_manager_preserves_full_login_cookie_header(monkeypatch):
    import kingdee_mcp.kingdee_session as session_module

    FakeAsyncClient.calls = []
    FakeAsyncClient.cookie_pairs = [
        ("kdservice-sessionid", "{session_id}"),
        ("ASP.NET_SessionId", "asp-{username}-{index}"),
    ]
    monkeypatch.setattr(session_module.httpx, "AsyncClient", FakeAsyncClient)
    cfg = ServiceConfig(
        server_url="https://example.com/k3cloud/",
        acct_id="acct",
        app_id="app",
        app_secret="secret",
        lcid=2052,
    )
    manager = KingdeeSessionManager(cfg, lambda: "https://example.com/login")

    assert await manager.get_session("user_a") == "session-user_a-1"
    assert await manager.get_cookie_header("user_a") == "kdservice-sessionid=session-user_a-1; ASP.NET_SessionId=asp-user_a-1"


@pytest.mark.asyncio
async def test_session_manager_refreshes_expired_ttl_before_reuse(monkeypatch):
    import kingdee_mcp.kingdee_session as session_module

    now = 1000.0
    FakeAsyncClient.calls = []
    FakeAsyncClient.cookie_pairs = []
    monkeypatch.setattr(session_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(session_module.time, "time", lambda: now)
    cfg = ServiceConfig(
        server_url="https://example.com/k3cloud/",
        acct_id="acct",
        app_id="app",
        app_secret="secret",
        lcid=2052,
        session_ttl_seconds=10,
    )
    manager = KingdeeSessionManager(cfg, lambda: "https://example.com/login")

    first = await manager.get_session("user_a")
    now = 1005.0
    still_fresh = await manager.get_session("user_a")
    now = 1011.0
    refreshed = await manager.get_session("user_a")

    assert first == "session-user_a-1"
    assert still_fresh == first
    assert refreshed == "session-user_a-2"
    assert FakeAsyncClient.calls == [
        ("https://example.com/login", "user_a"),
        ("https://example.com/login", "user_a"),
    ]
