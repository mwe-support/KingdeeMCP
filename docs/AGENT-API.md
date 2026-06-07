# KingdeeMCP Agent API

This document describes the current lightweight production MCP surface.
Legacy FastMCP write tools, SQL probing tools, and composite write workflows are not registered in the production entrypoint.

## Environment

Use `.env.example` and [configuration.md](configuration.md). Security defaults:

```text
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8199
MCP_PATH=/mcp
MCP_AUTH_DISABLED=false
```

HTTP production maps callers from `MCP_TOKEN_CONFIG`; do not use one global `KINGDEE_USERNAME` for shared remote deployment.

## Tool List

| Tool | Required / important parameters | Notes |
| --- | --- | --- |
| `kingdee_smoke_test` | `run_query=false` for login-only test | Verifies MCP auth and mapped Kingdee login. |
| `kingdee_query_bills` | `form_id`, optional `filter_string`, `field_keys`, `limit` | Generic read-only query. Default limit is 20. |
| `kingdee_view_bill` | `form_id`, `bill_id` | View one bill by FID. |
| `kingdee_query_purchase_orders` | optional `filter_string`, `limit` | Purchase order shortcut. |
| `kingdee_query_purchase_order_progress` | optional `filter_string`, `limit` | Purchase progress rows. |
| `kingdee_query_sale_orders` | optional `filter_string`, `limit` | Sale order shortcut. |
| `kingdee_query_stock_bills` | `form_id`, optional `filter_string`, `limit` | Stock bill query. |
| `kingdee_query_inventory` | optional `filter_string`, `limit` | Defaults to records with stock. |
| `kingdee_query_materials` | optional `filter_string`, `limit` | Material master data. |
| `kingdee_query_partners` | `partner_type=BD_Customer|BD_Supplier` | Customer or supplier master data. |
| `kingdee_list_forms` | optional `keyword` | Curated form catalog. |
| `kingdee_get_fields` | `form_id` | Recommended fields and optional metadata summary. |
| `kingdee_query_pending_approvals` | optional `form_id`, `status`, `limit` | Status-oriented read query. |
| `kingdee_query_workflow_status` | `form_id`, `bill_id` | View status for one bill. |

## Common Query Defaults

- `limit` defaults to 20 where supported.
- Query limits are capped by each tool schema, usually at 100.
- `kingdee_query_inventory` defaults to `FBaseQty>0`.
- Write, audit, delete, unaudit, push, and SQL probing calls should return unknown/disallowed in production.

## Error Handling

Tool errors are wrapped as MCP tool results with `isError=true` and a structured payload:

```json
{
  "ok": false,
  "error": {
    "type": "server_busy",
    "message": "Server is busy; retry later"
  }
}
```

Authentication failures are rejected before tool logic. Missing, invalid, or disabled Bearer tokens do not trigger Kingdee WebAPI calls.
