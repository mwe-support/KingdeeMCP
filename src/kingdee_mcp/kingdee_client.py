from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .auth import OperatorContext
from .config import ServiceConfig
from .kingdee_session import KingdeeSessionManager


_EP = {
    "login": "Kingdee.BOS.WebApi.ServicesStub.AuthService.LoginByAppSecret.common.kdsvc",
    "query": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.ExecuteBillQuery.common.kdsvc",
    "view": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.View.common.kdsvc",
    "metadata": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.QueryBusinessInfo.common.kdsvc",
    "save": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.Save.common.kdsvc",
    "submit": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.Submit.common.kdsvc",
    "audit": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.Audit.common.kdsvc",
    "unaudit": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.UnAudit.common.kdsvc",
    "delete": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.Delete.common.kdsvc",
    "push": "Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.Push.common.kdsvc",
    "user": "Kingdee.BOS.WebApi.ServicesStub.UserService.QueryUser.common.kdsvc",
    "role": "Kingdee.BOS.WebApi.ServicesStub.RoleService.QueryRole.common.kdsvc",
    "permission": "Kingdee.BOS.WebApi.ServicesStub.PermissionService.QueryPermission.common.kdsvc",
    "sequence": "Kingdee.BOS.WebApi.ServicesStub.SequenceRuleService.QuerySequenceRule.common.kdsvc",
    "number_rule": "Kingdee.BOS.WebApi.ServicesStub.NumberRuleService.QueryNumberRule.common.kdsvc",
    "sysconfig": "Kingdee.BOS.WebApi.ServicesStub.SystemConfigService.QuerySystemConfig.common.kdsvc",
}

_SESSION_EXPIRED_MARKERS = (
    "会话信息已丢失",
    "重新登录",
    "重新登陆",
    "未登录",
    "会话",
    "session",
    "not logged",
    "not login",
    "login again",
    "invalid session",
    "kdsvcsessionid",
)


class KingdeeWebAPIClient:
    """Small Kingdee WebAPI client shared by the lightweight MCP tools."""

    def __init__(self, config: ServiceConfig, *, max_concurrent_requests: int = 4, timeout: float = 30.0) -> None:
        self.config = config
        self.timeout = timeout
        self._max_concurrent_requests = max(1, int(max_concurrent_requests))
        self._session_manager = KingdeeSessionManager(config, lambda: self.url("login"))
        self._request_semaphore: asyncio.Semaphore | None = None

    def url(self, ep_key: str) -> str:
        return self.config.server_url.rstrip("/") + "/" + _EP[ep_key]

    def _semaphore(self) -> asyncio.Semaphore:
        if self._request_semaphore is None:
            self._request_semaphore = asyncio.Semaphore(self._max_concurrent_requests)
        return self._request_semaphore

    async def ensure_session(self, context: OperatorContext) -> str:
        return await self._session_manager.get_session(context.kingdee_username)

    async def refresh_session(self, context: OperatorContext) -> str:
        return await self._session_manager.refresh_session(context.kingdee_username)

    async def cookie_header(self, context: OperatorContext) -> str:
        return await self._session_manager.get_cookie_header(context.kingdee_username)

    async def refresh_cookie_header(self, context: OperatorContext) -> str:
        return await self._session_manager.refresh_cookie_header(context.kingdee_username)

    @staticmethod
    def is_session_expired_response(resp: httpx.Response) -> bool:
        text = resp.text or ""
        if resp.status_code == 401:
            return True
        if resp.status_code != 200:
            return False
        normalized = text.lower()
        return any(marker in normalized for marker in _SESSION_EXPIRED_MARKERS)

    @staticmethod
    def query_payload(
        form_id: str,
        field_keys: str,
        filter_string: str = "",
        order_string: str = "FID DESC",
        start_row: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        return {
            "FormId": form_id,
            "FieldKeys": field_keys,
            "FilterString": filter_string,
            "OrderString": order_string,
            "StartRow": start_row,
            "Limit": limit,
        }

    async def post(self, ep_key: str, payload: Any, context: OperatorContext) -> Any:
        if isinstance(payload, list) and len(payload) == 2:
            form_id, params = payload
            request_data = {"FormId": form_id, **params}
        else:
            request_data = payload

        async with self._semaphore():
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=None,
                transport=httpx.AsyncHTTPTransport(http1=True),
            ) as client:
                cookie_header = await self.cookie_header(context)
                resp = await client.post(
                    self.url(ep_key),
                    data={"data": json.dumps(request_data, ensure_ascii=False)},
                    headers={"Cookie": cookie_header},
                )
                if self.is_session_expired_response(resp):
                    cookie_header = await self.refresh_cookie_header(context)
                    resp = await client.post(
                        self.url(ep_key),
                        data={"data": json.dumps(request_data, ensure_ascii=False)},
                        headers={"Cookie": cookie_header},
                    )
                resp.raise_for_status()
                return resp.json()

    async def raw(self, ep_key: str, form_id: str, data_obj: dict[str, Any], context: OperatorContext) -> Any:
        body = json.dumps({"formid": form_id, "data": json.dumps(data_obj, ensure_ascii=False)}, ensure_ascii=False)
        async with self._semaphore():
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=None,
                transport=httpx.AsyncHTTPTransport(http1=True),
            ) as client:
                cookie_header = await self.cookie_header(context)
                resp = await client.post(
                    self.url(ep_key),
                    content=body.encode("utf-8"),
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "Cookie": cookie_header,
                    },
                )
                if self.is_session_expired_response(resp):
                    cookie_header = await self.refresh_cookie_header(context)
                    resp = await client.post(
                        self.url(ep_key),
                        content=body.encode("utf-8"),
                        headers={
                            "Content-Type": "application/json; charset=utf-8",
                            "Cookie": cookie_header,
                        },
                    )
                resp.raise_for_status()
                return resp.json()

    async def view(self, form_id: str, bill_id: str, context: OperatorContext) -> Any:
        return await self.raw("view", form_id, {"Id": bill_id}, context)

    async def metadata(self, form_id: str, context: OperatorContext) -> Any:
        return await self.post("metadata", {"FormId": form_id}, context)


def rows(result: Any) -> list[Any]:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        value = result.get("Result", result.get("data", []))
        return value if isinstance(value, list) else []
    return []


def simplify_view_result(data: Any) -> Any:
    if isinstance(data, dict):
        has_id = "Id" in data or "FID" in data
        has_number = "Number" in data
        has_mlt = "MultiLanguageText" in data
        if has_id and (has_number or has_mlt):
            slim: dict[str, Any] = {}
            if "Id" in data:
                slim["Id"] = data["Id"]
            if "FID" in data and "Id" not in slim:
                slim["Id"] = data["FID"]
            if "Number" in data:
                slim["Number"] = data["Number"]
            if has_mlt:
                for item in data.get("MultiLanguageText", []):
                    if isinstance(item, dict) and item.get("LocaleId") == 2052 and str(item.get("Name") or "").strip():
                        slim["Name"] = item["Name"]
                        break
            return slim
        return {key: simplify_view_result(value) for key, value in data.items()}
    if isinstance(data, list):
        return [simplify_view_result(item) for item in data]
    return data


def metadata_summary(payload: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"source": "QueryBusinessInfo"}
    data = payload.get("Result", {}).get("NeedReturnData") if isinstance(payload, dict) else None
    entries = data.get("Entrys") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        result["available"] = False
        return result

    main_fields: list[dict[str, Any]] = []
    entry_summaries: dict[str, Any] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("Key") or entry.get("Id") or "").strip()
        name = _localized_name(entry.get("Name")) or key
        fields = entry.get("Fields") or []
        slim_fields = [_slim_metadata_field(item) for item in fields if isinstance(item, dict)]
        if key == "FBillHead" or not entry.get("ParentKey"):
            if key == "FBillHead":
                main_fields.extend(slim_fields)
            elif key:
                entry_summaries[key] = {"caption": name, "field_count": len(slim_fields), "required": [f["name"] for f in slim_fields if f.get("must")]}
        elif key:
            entry_summaries[key] = {"caption": name, "field_count": len(slim_fields), "required": [f["name"] for f in slim_fields if f.get("must")]}

    result.update(
        {
            "available": True,
            "main_field_count": len(main_fields),
            "main_required_fields": [f["name"] for f in main_fields if f.get("must")],
            "main_fields": [f for f in main_fields if f.get("must") or f.get("lookup")][:80],
            "entry_count": len(entry_summaries),
            "entries": entry_summaries,
        }
    )
    return result


def _localized_name(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("Key") == 2052:
                return str(item.get("Value") or item.get("Name") or "")
        if value and isinstance(value[0], dict):
            return str(value[0].get("Value") or value[0].get("Name") or "")
    if isinstance(value, str):
        return value
    return ""


def _slim_metadata_field(field: dict[str, Any]) -> dict[str, Any]:
    key = str(field.get("Key") or field.get("FieldName") or field.get("Name") or "").strip()
    item: dict[str, Any] = {"name": key, "caption": _localized_name(field.get("Name")) or key}
    if field.get("MustInput") or field.get("IsMustInput"):
        item["must"] = True
    lookup = field.get("LookUpObjectFormId")
    if lookup:
        item["lookup"] = lookup
    return item
