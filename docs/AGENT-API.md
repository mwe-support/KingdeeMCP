# KingdeeMCP Agent API

This document describes the current lightweight production MCP surface.
Write tools and composite write workflows are registered in the lightweight entrypoint behind explicit write profiles. SQL probing is not registered in production.

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

## Experimental Read Tool

`kingdee_query_subledger` is registered for `full-read`, `read-all`, `write`, and explicit tool authorization. It is excluded from `read`, `core`, `all`, `high`, and `*` unless the token also names the tool explicitly.

Required parameters are `account_book_number`, `start_year`, `end_year`, and `start_account_number`. Important optional parameters are `start_period`, `end_period`, `end_account_number`, `currency_number`, `include_unposted_vouchers`, `exclude_adjustment_vouchers`, `balance_start_row`, `balance_limit`, `start_row`, and `limit`. The composite query supports ordinary periods 1-12.

The tool uses `ExecuteBillQuery` against two metadata-backed business objects:

- `GL_BALANCE` provides opening and closing accounting balances.
- `GL_VOUCHER` provides voucher entry details for the selected period and account range.

It does not call `GetSysReportData` for `GL_RPT_SubLedger`. The current environment rejects that complex report with `此接口暂时只支持简单账表`. The composite path has been validated against a real account-book result, but it intentionally does not reproduce UI-only behavior such as opposite-account matching, accounting-dimension expansion, period subtotal rows, or report-page navigation.

`GL_BALANCE` contains posted balances. With `include_unposted_vouchers=false` (default), voucher entries are filtered to records with a poster. Invalid vouchers are always excluded. With `include_unposted_vouchers=true`, returned entries can include amounts that are not reflected in the opening or closing balance rows. `exclude_adjustment_vouchers=true` is the default and applies matching adjustment filters to both `GL_BALANCE` and `GL_VOUCHER`. Use the independent balance and entry pagination parameters, and check `opening_balances_has_more`, `closing_balances_has_more`, and `has_more` before assuming the returned data is complete.

## Common Query Defaults

- `limit` defaults to 20 where supported.
- Query limits are capped by each tool schema, usually at 100.
- `kingdee_query_inventory` defaults to `FBaseQty>0`.
- Write, audit, delete, unaudit, push, and SQL probing calls should return unknown/disallowed in production.
- `kingdee_query_subledger` caps voucher entries at 100 rows and balance rows at 100 per boundary period to bound MCP response size.

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
