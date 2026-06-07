import pytest

from kingdee_mcp.config import ServiceConfig
from kingdee_mcp.kingdee_session import KingdeeSessionManager


class FakeResponse:
    def __init__(self, session_id):
        self._session_id = session_id

    def raise_for_status(self):
        return None

    def json(self):
        return {"LoginResultType": 1, "KDSVCSessionId": self._session_id}


class FakeAsyncClient:
    calls = []

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
        return FakeResponse(f"session-{username}-{len(self.calls)}")


@pytest.mark.asyncio
async def test_session_manager_caches_sessions_per_kingdee_user(monkeypatch):
    import kingdee_mcp.kingdee_session as session_module

    FakeAsyncClient.calls = []
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
