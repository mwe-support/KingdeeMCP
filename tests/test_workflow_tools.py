import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from kingdee_mcp.auth import OperatorContext
from kingdee_mcp.kingdee_client import KingdeeWebAPIClient, rows
from kingdee_mcp.light_tools import build_core_read_tools
from kingdee_mcp.mcp_lite import access_response_status, coerce_arguments, tool_result
from tests.test_lightweight_mcp import service_config


TASK = "6a9abe3f0a800e"
OTHER = "different-task"


class WorkflowClient:
    def __init__(self):
        self.status = "0"
        self.opinion = None
        self.calls = []
        self.filters = []

    async def current_user_id(self, context):
        return 103412

    query_payload = staticmethod(KingdeeWebAPIClient.query_payload)

    async def post(self, key, payload, context):
        assert key == "query"
        self.filters.append(payload["FilterString"])
        assert "FReceiverId = 103412" in payload["FilterString"]
        if OTHER in payload["FilterString"]:
            return []
        if "FStatus = '0'" in payload["FilterString"] and self.status != "0":
            return []
        return [["assign-1", TASK, "TEST_INSTANCE", "TEST_MATERIAL", "BD_MATERIAL",
                 "first approval", "0" if self.status == "0" else "1", "2",
                 103412, "test-user", self.status, self.opinion, None, 0, None, "2026-09-04"]]

    async def workflow_audit(self, payload, context):
        self.calls.append(payload)
        self.status = "1"
        self.opinion = payload["Disposition"]
        return {"Result": {"ResponseStatus": {"IsSuccess": True, "Errors": [], "SuccessEntitys": [{"Id": "assign-1"}]}}}

    async def raw(self, *args):
        raise AssertionError("Traditional audit/unaudit must not be called")


def context():
    return OperatorContext(operator="test-user", kingdee_username="test-user", allowed_tools=frozenset({"write"}))


@pytest.mark.asyncio
async def test_workflow_chain_uses_authenticated_user_and_verifies_opinion():
    client = WorkflowClient()
    registry = build_core_read_tools(client)
    listing = await registry["kingdee_workflow_tasks"].handler({"limit": 20, "start_row": 0}, context())
    assert listing["tasks"][0]["task_id"] == TASK
    assert "FStatus = '0'" in client.filters[-1]
    detail = await registry["kingdee_workflow_task"].handler({"task_id": TASK}, context())
    assert detail["task"]["receiver_id"] == 103412
    result = await registry["kingdee_workflow_approve"].handler({"task_id": TASK, "action": "approve", "opinion": "verified test"}, context())
    assert result["success"] is True
    assert result["verified"] is True
    assert client.calls == [{"FormId": "BD_MATERIAL", "Numbers": ["TEST_MATERIAL"], "UserId": 103412, "ApprovalType": 1, "Disposition": "verified test"}]
    assert result["after"]["opinion"] == "verified test"
    with pytest.raises(PermissionError):
        await registry["kingdee_workflow_approve"].handler({"task_id": TASK, "action": "approve"}, context())
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_foreign_task_and_malformed_task_never_write():
    client = WorkflowClient()
    registry = build_core_read_tools(client)
    for task_id in (OTHER, "x' OR 1=1 --", ""):
        with pytest.raises((ValueError, PermissionError)):
            await registry["kingdee_workflow_approve"].handler({"task_id": task_id, "action": "approve"}, context())
    assert client.calls == []
    schema = registry["kingdee_workflow_approve"].input_schema
    with pytest.raises(ValueError):
        coerce_arguments(schema, {"task_id": TASK, "user_id": 125169})


@pytest.mark.asyncio
async def test_reject_is_workflow_reject_not_unaudit():
    client = WorkflowClient()
    registry = build_core_read_tools(client)
    result = await registry["kingdee_workflow_approve"].handler({"task_id": TASK, "action": "reject", "opinion": "return for correction"}, context())
    assert result["verified"] is True
    assert client.calls[0]["ApprovalType"] == 2


def test_business_failure_reaches_mcp_and_access_log():
    failure = {"op": "audit", "success": False, "errors": [{"Message": "workflow required"}]}
    result = tool_result(failure)
    assert result["isError"] is True
    assert access_response_status(200, {"result": result}, "tools/call")[0] == "error"
    with pytest.raises(RuntimeError):
        rows([[{"Result": {"ResponseStatus": {"IsSuccess": False, "Errors": [{"Message": "invalid form"}]}}}]])


@pytest.mark.asyncio
async def test_workflow_write_is_not_retried_on_session_expiration(monkeypatch):
    import kingdee_mcp.kingdee_client as module

    seen = []
    real_client = httpx.AsyncClient

    def respond(request):
        seen.append(request)
        return httpx.Response(401, json={"Message": "session expired"})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport))
    client = KingdeeWebAPIClient(service_config())
    client.cookie_header = AsyncMock(return_value="kdservice-sessionid=test")
    client.current_user_id = AsyncMock(return_value=103412)
    with pytest.raises(httpx.HTTPStatusError):
        await client.workflow_audit({"FormId": "BD_MATERIAL", "Numbers": ["TEST_MATERIAL"], "UserId": 103412, "ApprovalType": 1, "Disposition": "test"}, context())
    assert len(seen) == 1
    assert seen[0].url.path.endswith("DynamicFormService.WorkflowAudit.common.kdsvc")
    body = json.loads(json.loads(seen[0].content)["data"])
    assert body["Disposition"] == "test"


@pytest.mark.asyncio
async def test_authenticated_user_id_is_cached_with_login(monkeypatch):
    import kingdee_mcp.kingdee_session as module
    from tests.test_kingdee_session import FakeAsyncClient, FakeResponse

    monkeypatch.setattr(FakeResponse, "json", lambda self: {"LoginResultType": 1, "KDSVCSessionId": self._session_id, "Context": {"UserId": 103412}})
    FakeAsyncClient.calls = []
    FakeAsyncClient.cookie_pairs = []
    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)
    manager = module.KingdeeSessionManager(service_config(), lambda: "https://example.com/login")
    assert await manager.get_user_id("test-user") == 103412
    assert await manager.get_user_id("test-user") == 103412
    assert len(FakeAsyncClient.calls) == 1

@pytest.mark.asyncio
async def test_duplicate_workflow_calls_write_only_once():
    class SlowClient(WorkflowClient):
        async def workflow_audit(self, payload, context):
            await asyncio.sleep(0.01)
            return await super().workflow_audit(payload, context)

    client = SlowClient()
    approve = build_core_read_tools(client)["kingdee_workflow_approve"].handler
    args = {"task_id": TASK, "action": "approve", "opinion": "one transition"}
    results = await asyncio.gather(approve(args, context()), approve(args, context()), return_exceptions=True)
    assert len(client.calls) == 1
    assert sum(isinstance(result, PermissionError) for result in results) == 1


@pytest.mark.asyncio
async def test_failed_or_ambiguous_write_is_not_reported_verified():
    class FailedClient(WorkflowClient):
        async def workflow_audit(self, payload, context):
            self.calls.append(payload)
            return {"Result": {"ResponseStatus": {"IsSuccess": False, "Errors": [{"Message": "denied"}]}}}

    client = FailedClient()
    result = await build_core_read_tools(client)["kingdee_workflow_approve"].handler({"task_id": TASK}, context())
    assert result["success"] is False
    assert tool_result(result)["isError"] is True
    assert len(client.calls) == 1

    class TimeoutClient(WorkflowClient):
        async def workflow_audit(self, payload, context):
            self.calls.append(payload)
            raise httpx.ReadTimeout("timeout")

    client = TimeoutClient()
    result = await build_core_read_tools(client)["kingdee_workflow_approve"].handler({"task_id": TASK}, context())
    assert result["outcome_unknown"] is True
    assert result["retry_write"] is False
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_ambiguous_pending_tasks_fail_before_write():
    class AmbiguousClient(WorkflowClient):
        async def post(self, key, payload, context):
            data = await super().post(key, payload, context)
            if "FStatus = '0'" in payload["FilterString"]:
                return data * 2
            return data

    client = AmbiguousClient()
    with pytest.raises(PermissionError, match="Ambiguous"):
        await build_core_read_tools(client)["kingdee_workflow_approve"].handler({"task_id": TASK}, context())
    assert client.calls == []


def test_workflow_tools_preserve_core_catalog_and_reject_legacy_write_shape():
    from kingdee_mcp.mcp_lite import tool_allowed
    from kingdee_mcp.light_tools import CORE_READ_TOOL_NAMES

    tools = build_core_read_tools(WorkflowClient())
    assert len(CORE_READ_TOOL_NAMES) == 14
    for name in ("kingdee_workflow_tasks", "kingdee_workflow_task"):
        assert not tool_allowed(name, frozenset({"read"}))
        assert tool_allowed(name, frozenset({"full-read"}))
        assert tool_allowed(name, frozenset({"write"}))
    assert not tool_allowed("kingdee_workflow_approve", frozenset({"full-read"}))
    with pytest.raises(ValueError, match="task_id"):
        coerce_arguments(tools["kingdee_workflow_approve"].input_schema, {"form_id": "BD_Material", "bill_id": "13008679"})


@pytest.mark.asyncio
async def test_malformed_task_response_is_not_an_empty_inbox():
    class MalformedClient(WorkflowClient):
        async def post(self, *args):
            return {"unexpected": "response"}

    with pytest.raises(RuntimeError, match="Unexpected"):
        await build_core_read_tools(MalformedClient())["kingdee_workflow_tasks"].handler({}, context())

@pytest.mark.asyncio
async def test_final_approval_reads_task_after_it_moves_to_history():
    class ArchivedClient(WorkflowClient):
        async def post(self, key, payload, context):
            history = payload["FormId"] == "WF_AssignmentHisBill_ProcManage"
            if (self.status == "1") != history:
                return []
            data = await super().post(key, payload, context)
            if history:
                for row in data:
                    row[7] = "1"
            return data

    client = ArchivedClient()
    tools = build_core_read_tools(client)
    result = await tools["kingdee_workflow_approve"].handler(
        {"task_id": TASK, "action": "approve", "opinion": "final approval"}, context())
    assert result["success"] is True
    assert result["verified"] is True
    assert result["after"]["instance_status"] == "1"
    detail = await tools["kingdee_workflow_task"].handler({"task_id": TASK}, context())
    assert detail["task"]["opinion"] == "final approval"
    assert detail["task"]["can_process"] is False
    history = await tools["kingdee_workflow_tasks"].handler({"status": "history"}, context())
    assert history["tasks"][0]["task_id"] == TASK
    with pytest.raises(PermissionError):
        await tools["kingdee_workflow_approve"].handler({"task_id": TASK}, context())
    assert len(client.calls) == 1
