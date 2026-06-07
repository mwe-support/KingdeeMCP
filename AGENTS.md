# AGENTS.md

This file guides future agent work in this repository. Read it before changing
KingdeeMCP.

## Repository Purpose

KingdeeMCP is a Python MCP server that exposes Kingdee Cloud Star / K3Cloud
WebAPI operations as MCP tools for AI clients.

Primary files:

- `src/kingdee_mcp/server.py`: main MCP server, tool registration, Kingdee
  WebAPI calls, login/session handling, usage logging, and optional SQL Server
  helpers.
- `README.md`: install and user configuration.
- `.mcp.json.example`: current local stdio MCP example.
- `docs/permission-architecture.md`: design reference only. Do not assume it is
  already implemented.
- `pyproject.toml`: package metadata and `kingdee-mcp` console entry point.

## Current Baseline

Current MCP transport:

- Production console entrypoint is `kingdee_mcp.main:main`.
- Production HTTP uses the lightweight dispatcher in `mcp_lite.py` with
  `ThreadingHTTPServer`, ordinary JSON-RPC responses, and explicit
  `Content-Length`.
- Production HTTP must stay bound to `127.0.0.1`; external access should go
  through Cloudflare Tunnel/Access.
- Local stdio uses the same lightweight dispatcher and MCP content-length
  framing.
- Legacy `server.py` / FastMCP remains reference-only during the transition.

Current Kingdee authentication:

- Kingdee login uses `LoginByAppSecret`.
- Current global environment variables:
  - `KINGDEE_SERVER_URL`
  - `KINGDEE_ACCT_ID`
  - `KINGDEE_USERNAME` only for local stdio/check fallback
  - `KINGDEE_APP_ID`
  - `KINGDEE_APP_SEC`
  - `KINGDEE_LCID`
- `_login()` sends `[ACCT_ID, USERNAME, APP_ID, APP_SEC, LCID]`.
- Login returns `KDSVCSessionId`.
- Later requests send `Cookie: kdservice-sessionid=<session>`.
- `_session_id` is global, so the current process effectively represents one
  Kingdee user.

Important runtime details:

- Kingdee requests must use HTTP/1.1. Keep
  `httpx.AsyncHTTPTransport(http1=True)` unless a real Kingdee environment
  proves otherwise.
- Session expiration is detected by HTTP 401 or response text containing session
  expiration hints, then retried after relogin.
- SQL Server probing via `MCP_SQLSERVER_*` is legacy-only and out of scope for
  the first lightweight production entrypoint.

## Business Context

The Kingdee administrator has configured a third-party system login
authorization in the Kingdee Open Platform:

- One application has an AppID and AppSecret.
- Multiple Kingdee users are enabled under "specified user login".

This supports the desired model:

```text
Shared AppID/AppSecret + dynamic Kingdee username
```

The browser login state on `open.kingdee.com` is only for managing third-party
authorization. Do not use browser cookies or localStorage tokens as MCP runtime
credentials.

## Target Architecture

The goal is to support remote MCP deployment so client machines do not need a
local Python environment or local `kingdee-mcp` package installation.

Target flow:

```text
AI client
  -> Streamable HTTP MCP endpoint
  -> MCP Bearer Token authentication
  -> Token maps to operator and kingdee_username
  -> LoginByAppSecret(acct_id, kingdee_username, app_id, app_secret, lcid)
  -> Per-Kingdee-user session cache
  -> Kingdee WebAPI call
```

There are two authentication layers:

1. MCP ingress authentication: decides who may call the MCP server.
2. Kingdee WebAPI authentication: decides which Kingdee user performs the ERP
   operation.

Bearer Token must not only mean "can access MCP". In this deployment, it must
map to a specific Kingdee user.

## Planned Authentication Model

Keep shared service/app config in environment variables:

```text
KINGDEE_SERVER_URL=https://example.com/k3cloud/
KINGDEE_ACCT_ID=...
KINGDEE_APP_ID=...
KINGDEE_APP_SEC=<kingdee-app-secret>
KINGDEE_LCID=2052
```

For remote multi-user deployment, do not use one global `KINGDEE_USERNAME`.
Resolve `kingdee_username` from the authenticated Bearer Token.

Recommended token mapping shape:

```json
{
  "tokens": {
    "sha256:<hash>": {
      "operator": "zhangsan",
      "kingdee_username": "zhangsan",
      "enabled": true,
      "allowed_tools": ["read", "save"]
    },
    "sha256:<hash2>": {
      "operator": "lisi",
      "kingdee_username": "lisi",
      "enabled": true,
      "allowed_tools": ["read", "audit"]
    }
  }
}
```

Security requirements:

- Store token hashes, not plaintext Bearer Tokens.
- Never log Bearer Tokens, AppSecret, SessionId, cookies, or Authorization
  headers.
- Support revocation by disabling or removing a token mapping.
- Keep AppID/AppSecret only on the server or in a secret manager.
- Production must use HTTPS, preferably behind a reverse proxy or API gateway.

## Required Code Direction

Keep changes focused. Most current behavior is concentrated in `server.py`;
refactor gradually and keep every step verifiable.

Core changes needed:

1. Add transport configuration.
   - Keep stdio for local development and compatibility.
   - Add Streamable HTTP for remote deployment.
   - Use explicit lightweight env vars such as `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, and
     `MCP_PATH`; production should bind to `127.0.0.1:8199`.

2. Add MCP request authentication.
   - Read `Authorization: Bearer <token>`.
   - Hash the token and look it up in the token mapping.
   - Resolve an `OperatorContext` with at least `operator`, `kingdee_username`,
     and tool permission policy.
   - If legacy FastMCP is revisited, authenticate in
     an ASGI wrapper or reverse proxy and inject only trusted identity
     downstream. Do not let clients self-report `kingdee_username` in tool
     parameters.

3. Replace global single-user Session handling.
   - `_session_id` is not suitable for multi-user HTTP service.
   - Add a session cache keyed by
     `(server_url, acct_id, app_id, kingdee_username)`.
   - Use a per-key async lock so concurrent first requests for the same user do
     not trigger multiple logins.
   - If one user's session expires, relogin only that user.

4. Make Kingdee login identity explicit.
   - Add a small object such as `KingdeeIdentity`, `KingdeeAuthContext`, or
     `OperatorContext`.
   - `_login()` should accept `kingdee_username` or a context object instead of
     reading only global `USERNAME`.
   - `_post()` and `_post_raw()` should use the current operator context to get
     the correct session.

5. Add tool authorization.
   - Suggested risk groups:
     - `read`: query, view, metadata, user, role, permission, system info.
     - `write`: save, submit, push.
     - `high`: audit, unaudit, delete, create-and-audit, push-and-audit.
   - Enforce MCP-side permissions before calling Kingdee.
   - High-risk tools should eventually support an approval flow. First version
     may deny by default unless explicitly allowed.

6. Improve audit logs.
   - Log `operator`, `kingdee_username`, `tool_name`, `form_id`, result,
     duration, and sanitized parameter summary.
   - Do not log secrets or full sensitive business payloads.

## Configuration Suggestions

Remote deployment example:

```text
KINGDEE_SERVER_URL=https://example.com/k3cloud/
KINGDEE_ACCT_ID=...
KINGDEE_APP_ID=...
KINGDEE_APP_SEC=<kingdee-app-secret>
KINGDEE_LCID=2052
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8199
MCP_PATH=/mcp
MCP_TOKEN_CONFIG=/public/KingdeeMCP/secrets/tokens.json
MCP_AUTH_DISABLED=false
MCP_MAX_CONCURRENT_TOOLS=8
MCP_MAX_CONCURRENT_KINGDEE_REQUESTS=4
MCP_TOOL_QUEUE_TIMEOUT_SECONDS=3
MCP_TOOL_CALL_TIMEOUT_SECONDS=120
MCP_HTTP_REQUEST_QUEUE_SIZE=128
```

Do not carry legacy FastMCP/SQL/logging variables into the lightweight
production `.env` unless that feature is intentionally reintroduced. See `docs/configuration.md` for the full current environment contract.

Local development example:

```text
MCP_TRANSPORT=stdio
KINGDEE_USERNAME=<single-test-user>
```

If single-user stdio fallback remains, document that it is not suitable for
shared remote deployment.

## Deployment Principles

Production-like deployment should use:

- Streamable HTTP MCP endpoint.
- HTTPS.
- Bearer Token, enterprise SSO, or API gateway authentication at MCP ingress.
- Private network, IP allowlist, or VPN when possible.
- Process supervision through systemd, supervisor, Docker, or similar.
- Secrets supplied by environment variables or a secret manager, not committed
  files.

Do not expose an unauthenticated MCP HTTP endpoint to the public internet.

## Verification Checklist

Before authentication and multi-user work is considered complete, verify:

- A valid token maps to the expected `operator` and `kingdee_username`.
- An invalid token is rejected before tool logic runs.
- Disabled tokens are rejected.
- Two different tokens can log in as two different Kingdee users.
- Different Kingdee users have separate cached sessions.
- One user's expired session does not affect another user.
- A Kingdee user without ERP permission receives a Kingdee permission failure,
  not a successful operation.
- A caller without MCP tool permission is blocked before any Kingdee API call.
- Logs contain operator and Kingdee username, but no token, AppSecret,
  SessionId, or cookie.

Early Kingdee validation:

```text
LoginByAppSecret(ACCT_ID, user_a, APP_ID, APP_SEC, LCID)
LoginByAppSecret(ACCT_ID, user_b, APP_ID, APP_SEC, LCID)
```

Both should succeed only when the users are active, authorized, and included in
the Open Platform specified-user-login list.

## Development Rules

- Preserve existing MCP tool names unless a breaking change is explicitly
  planned.
- Prefer small, verifiable changes.
- Prefer typed helper objects for auth/session context over loose strings.
- Do not change Kingdee request formatting unless verified against a real
  Kingdee environment.
- Treat save, submit, audit, unaudit, delete, and push operations as high-risk
  surfaces.
- Keep read-only and write/high-risk tools clearly separated in code and docs.
- New config examples must use placeholders only.
- Never commit real tokens, AppSecret, SessionId, cookies, phone numbers, or
  environment-specific secrets.

## Recommended Work Order

1. Maintain this `AGENTS.md`.
2. Add Streamable HTTP transport while keeping stdio fallback.
3. Add Bearer Token authentication and token mapping config.
4. Refactor Kingdee login and session cache by `kingdee_username`.
5. Add tool risk classification and MCP-side authorization checks.
6. Add audit fields for `operator` and `kingdee_username`.
7. Add a multi-user `LoginByAppSecret` validation command or script.
8. Add systemd, Docker, and reverse proxy deployment examples.
9. Later: integrate enterprise SSO or a central identity service.
10. Later: add approval workflow for high-risk ERP operations.

## Tool Catalog Size Policy

The remote MCP deployment must keep the default client-visible tool catalog
small. Large `tools/list` payloads can cause MCP clients to spend excessive
memory parsing and indexing schemas.

Current policy:

- Bearer tokens with `allowed_tools: ["read"]` see only `_CORE_READ_TOOLS`.
- Bearer tokens with `allowed_tools: ["write"]` or `["core"]` see
  `_CORE_READ_TOOLS | _CORE_WRITE_TOOLS`.
- Bearer tokens with `high`, `all`, or `*` see the full catalog and should be
  reserved for trusted admin/development use.
- Explicit tool names may be used to grant individual non-core tools.
- Keep the default catalog between 10 and 20 tools. If a new business module
  adds many tools, prefer a compact generic tool or a separate profile instead
  of expanding `read`/`write` broadly.

After changing tools or profiles, run:

```bash
.venv/bin/python -m pytest tests/test_tool_profiles.py tests/test_auth_mapping.py tests/test_token_cli.py tests/test_kingdee_session.py -q
```

## Lightweight MCP Gateway Refactor

The production `kingdee-mcp` entrypoint is being refactored toward a Lingxing-style lightweight gateway.

Design rules for this refactor:

- Production HTTP MCP must use ordinary JSON-RPC short responses:
  - `Content-Type: application/json; charset=utf-8`
  - explicit `Content-Length`
  - no `text/event-stream`
  - no `mcp-session-id`
- The protocol layer should use Python standard library primitives (`http.server`, JSON, stdio content-length framing).
- Do not import FastMCP, Starlette, uvicorn, or Pydantic from the production entrypoint.
- Keep Kingdee WebAPI authentication separate from MCP ingress authentication:
  - MCP Bearer Token authenticates the caller.
  - The token mapping resolves `operator` and `kingdee_username`.
  - Kingdee WebAPI still uses `LoginByAppSecret(acct_id, kingdee_username, app_id, app_secret, lcid)`.
  - Cache Kingdee sessions per Kingdee user and refresh only the affected user when a session expires.
- Keep `httpx` for Kingdee WebAPI calls and force HTTP/1.1.
- First lightweight production version exposes only the curated read-only tool surface:
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
- Write, audit, unaudit, delete, push, SQL probe, and legacy full-catalog tools are out of scope for the first lightweight production entrypoint.
- Local stdio should use the same lightweight dispatcher as HTTP. It may use `KINGDEE_USERNAME` as the local user when no HTTP Bearer context exists.
- Keep the old FastMCP `server.py` only as legacy reference/compatibility during transition; do not add new production behavior there unless explicitly requested.
