# CLAUDE.md

This file guides agents working in this repository.

## Current Architecture

The production entrypoint is `kingdee_mcp.main:main`.
It runs the lightweight MCP dispatcher in `src/kingdee_mcp/mcp_lite.py`.

Production HTTP behavior:

- `ThreadingHTTPServer` on `MCP_HOST` / `MCP_PORT` / `MCP_PATH`.
- Recommended secure bind is `MCP_HOST=127.0.0.1` and `MCP_PORT=8199`.
- JSON-RPC responses use `application/json` and `Content-Length`.
- No SSE, no `mcp-session-id`, no Starlette or uvicorn in the production entrypoint.

Kingdee behavior:

- Shared AppID/AppSecret stay in environment variables.
- MCP Bearer tokens map to `operator`, `kingdee_username`, and `allowed_tools`.
- Kingdee login uses `LoginByAppSecret(acct_id, kingdee_username, app_id, app_secret, lcid)`.
- Sessions are cached per Kingdee user and refresh proactively after `KINGDEE_SESSION_TTL_SECONDS` (default `1200`).
- Later Kingdee API calls send the full login Cookie header, preserving `kdservice-sessionid` and any extra cookies returned by Kingdee, such as `ASP.NET_SessionId`.
- `httpx` must keep HTTP/1.1 for Kingdee WebAPI calls.

## Commands

```bash
# Install lightweight production dependencies in development mode
pip install -e .

# Run the MCP server directly; reads .env when systemd loads it, or shell env in local runs
kingdee-mcp

# Check local Kingdee login using KINGDEE_USERNAME fallback
kingdee-mcp --check

# Run focused lightweight tests
python -m pytest tests/test_lightweight_mcp.py tests/test_auth_mapping.py tests/test_token_cli.py tests/test_kingdee_session.py -q
```


## Environment Variables

Use `docs/configuration.md` as the source of truth. Every production `.env` should keep the MCP origin local-only:

```env
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8199
MCP_PATH=/mcp
MCP_AUTH_DISABLED=false
```

`KINGDEE_USERNAME` is only a local stdio, `--check`, or unauthenticated-test fallback. HTTP production resolves the Kingdee user from `MCP_TOKEN_CONFIG`.

## Current Tool Surface

The lightweight registry contains the migrated read, write, and ops tool names. A default `read` token exposes only these 14 core read-only tools:

- `kingdee_smoke_test`
- `kingdee_query_bills`
- `kingdee_view_bill`
- `kingdee_query_purchase_orders`
- `kingdee_query_purchase_order_progress`
- `kingdee_query_sale_orders`
- `kingdee_query_stock_bills`
- `kingdee_query_inventory`
- `kingdee_query_materials`
- `kingdee_query_partners`
- `kingdee_list_forms`
- `kingdee_get_fields`
- `kingdee_query_pending_approvals`
- `kingdee_query_workflow_status`

`full-read` exposes the migrated read-only catalog. Write, audit, unaudit, delete, and push tools require the `write`, `all`, `high`, explicit tool-name profile, or equivalent token entry. SQL probing and in-process usage logs are represented only by lightweight ops placeholders.

## Files To Prefer

- `src/kingdee_mcp/mcp_lite.py`: lightweight MCP protocol layer.
- `src/kingdee_mcp/light_tools.py`: lightweight tool registry and schemas.
- `src/kingdee_mcp/kingdee_client.py`: Kingdee WebAPI wrapper.
- `src/kingdee_mcp/kingdee_session.py`: per-user Kingdee session cache.
- `src/kingdee_mcp/auth.py`: Bearer token hashing and mapping.
- `src/kingdee_mcp/config.py`: environment loading.

## Safety Rules

- Never print real `.env`, AppSecret, Bearer token plaintext, Cloudflare Access secret, or Kingdee session cookies.
- Do not bind production MCP directly to `0.0.0.0`.
- Do not add new production dependencies on Starlette, uvicorn, or Pydantic without explicit approval.
