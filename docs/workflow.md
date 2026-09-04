# Workflow Approval

The lightweight gateway uses the official Kingdee `DynamicFormService.WorkflowAudit`
endpoint, not traditional `Audit` or `UnAudit`.
The existing Bearer mapping and LoginByAppSecret cookies remain in use.

## Tools

- `kingdee_workflow_tasks`: current authenticated user's tasks; defaults to
  pending tasks in running instances. Optional exact `form_id`, `bill_number`,
  `status=pending|all|history`, `start_row`, and `limit` (20 by default, at most 100).
- `kingdee_workflow_task`: requires `task_id`; returns only that user's
  receiver task, including instance, node, bill number, status, and saved opinion. Detail
  falls back to history after completion, under the same user filter.
- `kingdee_workflow_approve`: requires `task_id`; `action=approve|reject`,
  optional `opinion` (at most 1000 characters), and optional `form_id` /
  `bill_id` consistency checks. If bill_id is supplied, the write uses that
  verified bill ID; otherwise it uses the task's bill number.

The task_id is the receiver-item ID, not the material/bill ID or workflow instance
ID. Legacy calls containing only form_id and bill_id now fail validation.
Refresh the MCP client tool catalog after deployment.

## Identity and Authorization

UserId comes from the authenticated LoginByAppSecret response Context.UserId.
Clients cannot choose an approver ID, impersonate another receiver, or supply a
raw workflow filter. Listing, detail, and pre-write validation always scope to
that ID. A token's MCP role alone does not grant Kingdee task-processing rights.

The two read tools belong to full-read/read-all/write/all/high or explicit
authorization. Workflow approval remains a write-profile tool. The default
read/core catalog stays at 14 tools.

This instance exposes task metadata through ExecuteBillQuery on
`WF_AssignmentBill_ProcManage` (active instances) and
`WF_AssignmentHisBill_ProcManage` (history). `status=all` means all task
states in active instances; `status=history` lists archived instances.
Pagination is independent per source, identified by `source_form`. Each deployment must permit its users to read
this object; permission or metadata errors fail rather than masquerading as an
empty inbox. No direct database access or browser cookies are used.

## Workflow Semantics

- Approve uses ApprovalType 1; reject uses ApprovalType 2. Reject is not UnAudit.
- The opinion is sent as Disposition and compared with the task's saved opinion.
- Pending means task status 0, node status 0, and instance status 2.
- A processed task does not imply the entire bill is audited: later nodes may
  remain pending and the bill can remain in status B.
- The old `kingdee_query_pending_approvals` and
  `kingdee_query_workflow_status` are bill-status queries, not personal inboxes.
- A write is issued only after a fresh, unambiguous pending-task check. Workflow
  writes are serialized in this process. The upstream API addresses bills/users,
  not a conditional receiver-task version; external-client races cannot be made
  atomic by this gateway. Avoid simultaneous UI and MCP approvals of one bill.

## Results and Retries

Business success=false/ok=false and raw failed ResponseStatus results produce
MCP isError=true and an error access-log status. Query business errors are raised
before row counting. HTTP 200 alone never proves business success.

Workflow writes are never automatically retried, including session expiry and
transport timeouts. On outcome_unknown, inspect the same task before deciding
what to do. An accepted response returns success=true; verified=true additionally
requires task status 1 and a matching persisted opinion. verification_status
pending is not permission to resend. The gateway does not terminate workflows,
skip nodes, transfer tasks, or rewrite bill states.

## Verification

Use only explicitly authorized, purpose-created test materials. Verify the
identity, assigned task, and bill before approval; compare task state and saved
opinion afterward, then inspect the actual next node in the browser.

Official reference:
[WebAPI workflow approval example](https://vip.kingdee.com/knowledge/specialDetail/650386937144032256?category=650388108193709056&id=353544491246352128&type=Knowledge&productLineId=1&lang=zh-CN).
