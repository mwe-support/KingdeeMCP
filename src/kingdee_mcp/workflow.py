from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from .auth import OperatorContext
from .kingdee_client import KingdeeWebAPIClient, rows, raise_business_error


TASK_FORM = "WF_AssignmentBill_ProcManage"
HISTORY_FORM = "WF_AssignmentHisBill_ProcManage"
READ_TOOL_NAMES = frozenset({"kingdee_workflow_tasks", "kingdee_workflow_task"})
_TASK_FIELDS = (
    ("FAssignId", "assignment_id"),
    ("FReceiverItem_FRECEIVERITEMID", "task_id"),
    ("FInstCode", "instance_code"),
    ("FBILLNUMBER", "bill_number"),
    ("FObjectTypeId", "form_id"),
    ("FASSIGNNAME", "node_name"),
    ("FActivityStatus", "node_status"),
    ("FInstStatus", "instance_status"),
    ("FReceiverId", "receiver_id"),
    ("FReceiverId.FName", "receiver_name"),
    ("FStatus", "task_status"),
    ("FDisposition", "opinion"),
    ("FResultName", "result_name"),
    ("FBasePost", "post_id"),
    ("FCompletedTime", "completed_at"),
    ("FCreateTime", "created_at"),
)
FIELD_KEYS = ",".join(field for field, _ in _TASK_FIELDS)


def _identifier(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", text):
        raise ValueError(f"{label} must be a nonempty identifier")
    return text


def _quote(value: str) -> str:
    if len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ValueError("Invalid workflow filter value")
    return "'" + value.replace("'", "''") + "'"


def _pending(task: dict[str, Any]) -> bool:
    return (task.get("source_form", TASK_FORM) == TASK_FORM and task["task_status"] == "0"
            and task["node_status"] == "0" and task["instance_status"] == "2")


class WorkflowService:
    def __init__(self, client: KingdeeWebAPIClient):
        self.client = client
        # ponytail: serialize workflow writes per process; use keyed locks only if throughput requires it.
        self._write_lock = asyncio.Lock()

    async def _query(self, context: OperatorContext, *, task_id: str = "", form_id: str = "",
                     bill_number: str = "", pending: bool = False, start_row: int = 0,
                     limit: int = 20, history: bool = False) -> list[dict[str, Any]]:
        user_id = await self.client.current_user_id(context)
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise PermissionError("Authenticated Kingdee user ID is unavailable")
        terms = [f"FReceiverId = {user_id}"]
        if task_id:
            terms.append("FReceiverItem_FRECEIVERITEMID = " + _quote(_identifier(task_id, "task_id")))
        if form_id:
            terms.append("FObjectTypeId = " + _quote(_identifier(form_id, "form_id").upper()))
        if bill_number:
            terms.append("FBILLNUMBER = " + _quote(bill_number))
        if pending:
            terms.extend(["FStatus = '0'", "FActivityStatus = '0'", "FInstStatus = '2'"])
        source_form = HISTORY_FORM if history else TASK_FORM
        payload = self.client.query_payload(source_form, FIELD_KEYS, " AND ".join(terms),
                                           "FCreateTime DESC,FAssignId DESC,FReceiverItem_FRECEIVERITEMID DESC",
                                           start_row, limit)
        raw = await self.client.post("query", payload, context)
        raise_business_error(raw)
        if not isinstance(raw, list):
            raise RuntimeError("Unexpected workflow query response")
        data = rows(raw)
        output = []
        for row in data:
            if not isinstance(row, list) or len(row) != len(_TASK_FIELDS):
                raise RuntimeError("Unexpected workflow task response")
            task = dict(zip((name for _, name in _TASK_FIELDS), row))
            if str(task["receiver_id"]) != str(user_id):
                raise PermissionError("Workflow response contains another user's task")
            if task_id and str(task["task_id"]) != task_id:
                raise RuntimeError("Workflow task identity mismatch")
            for key in ("task_status", "node_status", "instance_status"):
                task[key] = str(task[key])
            task["receiver_id"] = user_id
            task["source_form"] = source_form
            task["can_process"] = _pending(task)
            output.append(task)
        return output

    async def list_tasks(self, args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        limit = int(args.get("limit", 20))
        offset = int(args.get("start_row", 0))
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid workflow pagination")
        status = args.get("status", "pending")
        if status not in {"pending", "all", "history"}:
            raise ValueError("status must be pending, all (active instances), or history")
        data = await self._query(context, form_id=args.get("form_id", ""),
                                 bill_number=args.get("bill_number", ""), pending=status == "pending",
                                 start_row=offset, limit=limit + 1, history=status == "history")
        return {"operator": context.operator, "kingdee_username": context.kingdee_username,
                "start_row": offset, "count": min(len(data), limit), "has_more": len(data) > limit,
                "tasks": data[:limit], "source_form": HISTORY_FORM if status == "history" else TASK_FORM}

    async def task_detail(self, args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        task_id = _identifier(args.get("task_id"), "task_id")
        matches = await self._query(context, task_id=task_id, limit=2)
        if not matches:
            matches = await self._query(context, task_id=task_id, limit=2, history=True)
        if len(matches) != 1:
            raise PermissionError("Task not found or not assigned to the authenticated user")
        return {"task": matches[0]}

    async def approve(self, args: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        task_id = _identifier(args.get("task_id"), "task_id")
        action = args.get("action", "approve")
        if action not in {"approve", "reject"}:
            raise ValueError("action must be approve or reject")
        opinion = str(args.get("opinion") or "").strip()
        if len(opinion) > 1000:
            raise ValueError("opinion must be at most 1000 characters")
        async with self._write_lock:
            before = (await self.task_detail({"task_id": task_id}, context))["task"]
            if not _pending(before):
                raise PermissionError("Task is not pending in a running workflow; do not retry")
            if args.get("form_id") and args["form_id"].upper() != before["form_id"].upper():
                raise ValueError("form_id does not match the task")
            if not str(before["bill_number"] or "").strip():
                raise RuntimeError("Workflow task has no bill number")
            candidates = await self._query(context, form_id=before["form_id"],
                                           bill_number=before["bill_number"], pending=True, limit=2)
            if len(candidates) != 1 or candidates[0]["task_id"] != task_id:
                raise PermissionError("Ambiguous or changed pending tasks; inspect the task before approving")
            payload = {"FormId": before["form_id"], "Numbers": [before["bill_number"]],
                       "UserId": before["receiver_id"], "ApprovalType": 1 if action == "approve" else 2,
                       "Disposition": opinion}
            if args.get("bill_id"):
                viewed = await self.client.view(before["form_id"], str(args["bill_id"]), context)
                raise_business_error(viewed)
                model = viewed.get("Result", {}).get("Result", {})
                if str(model.get("Number") or model.get("FBillNo") or "") != before["bill_number"]:
                    raise ValueError("bill_id does not match the task")
                payload.pop("Numbers")
                payload["Ids"] = str(args["bill_id"])
            if before["post_id"]:
                payload["PostId"] = int(before["post_id"])
            try:
                response = await self.client.workflow_audit(payload, context)
            except (httpx.HTTPError, ValueError) as exc:
                return {"success": False, "outcome_unknown": True, "retry_write": False,
                        "task_id": task_id, "error": {"type": "workflow_outcome_unknown",
                        "message": f"{type(exc).__name__}: read task state before any further write"}}
            status = response.get("Result", {}).get("ResponseStatus") if isinstance(response, dict) else None
            if not isinstance(status, dict) or type(status.get("IsSuccess")) is not bool:
                return {"success": False, "outcome_unknown": True, "retry_write": False,
                        "task_id": task_id, "error": {"type": "workflow_outcome_unknown",
                        "message": "Unexpected WorkflowAudit response; read task state before any further write"}}
            if status["IsSuccess"] is False:
                return {"success": False, "op": "workflow_audit", "task_id": task_id,
                        "response_status": status, "errors": status.get("Errors", []), "retry_write": False}
            after = None
            verification_error = None
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(0.3)
                try:
                    after = (await self.task_detail({"task_id": task_id}, context))["task"]
                    verification_error = None
                except Exception as exc:
                    verification_error = type(exc).__name__
                    continue
                if after["task_status"] == "1":
                    break
            verified = bool(after and after["task_status"] == "1" and str(after["opinion"] or "").strip() == opinion)
            return {"success": True, "op": "workflow_audit", "action": action, "task_id": task_id,
                    "before": before, "after": after, "verified": verified,
                    "verification_status": "verified" if verified else "pending",
                    "verification_error": verification_error, "retry_write": False,
                    "response_status": status}
