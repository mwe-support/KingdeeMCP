# KingdeeMCP Lightweight Configuration

This document is the source of truth for the current lightweight production entrypoint.
The production command is `kingdee-mcp`, which imports `kingdee_mcp.main:main` and runs the lightweight dispatcher in `mcp_lite.py`.

## Security Defaults

- `MCP_HOST` should be `127.0.0.1`.
- `MCP_PORT` should be `8199`.
- Do not publish the MCP origin port directly on the server.
- Expose remote access through Cloudflare Tunnel/Access and keep the local origin bound to localhost.
- MCP Bearer tokens are checked by KingdeeMCP; Cloudflare Access is an additional edge protection layer.

## Required Kingdee WebAPI Variables

| Variable | Required | Recommended value | Description |
| --- | --- | --- | --- |
| `KINGDEE_SERVER_URL` | yes | `https://your-kingdee-host/k3cloud/` | Kingdee K/3 Cloud WebAPI base URL. It must include `/k3cloud/`. |
| `KINGDEE_ACCT_ID` | yes | account set id | Account set id passed to `LoginByAppSecret`. |
| `KINGDEE_APP_ID` | yes | app id | Third-party system application id from Kingdee admin. |
| `KINGDEE_APP_SEC` | yes | app secret | Third-party system application secret. Keep it server-side only. |
| `KINGDEE_LCID` | no | `2052` | Locale id. `2052` is Simplified Chinese. |
| `KINGDEE_USERNAME` | local only | empty in HTTP production | Fallback user for local stdio, `--check`, or `MCP_AUTH_DISABLED=true`. HTTP production maps users from Bearer tokens. |
| `KINGDEE_SESSION_TTL_SECONDS` | no | `1200` | Proactive per-Kingdee-user session refresh window. After this many seconds, the next call logs in again before calling Kingdee. Set `0` only to disable TTL intentionally. |

Login responses are cached per mapped Kingdee user. The lightweight client sends the full login cookie header on later API calls, including `kdservice-sessionid` and any additional cookies returned by Kingdee such as `ASP.NET_SessionId`.

## Required MCP Transport Variables

| Variable | Required | Recommended value | Description |
| --- | --- | --- | --- |
| `MCP_TRANSPORT` | yes | `streamable-http` | Runs the lightweight HTTP gateway. Use `stdio` only for local client tests. |
| `MCP_HOST` | yes | `127.0.0.1` | Local bind address. Keep localhost-only for security. |
| `MCP_PORT` | yes | `8199` | Local MCP origin port used by systemd and cloudflared. |
| `MCP_PATH` | yes | `/mcp` | JSON-RPC MCP endpoint path. |
| `MCP_TOKEN_CONFIG` | yes for HTTP production | `/public/KingdeeMCP/secrets/tokens.json` | JSON file containing SHA-256 token hashes and Kingdee user mapping. |
| `MCP_AUTH_DISABLED` | no | `false` | Set `true` only for local unauthenticated tests. Never enable in shared production. |
| `MCP_CORS_ALLOW_ORIGINS` | no | `*` | Comma-separated browser/WebView origins allowed by the lightweight gateway. Use `*` for broad client compatibility, or an explicit list such as `http://localhost:6274,https://your-client.example.com`. With Cloudflare Access, enable `options_preflight_bypass` and leave Access-level CORS unset so the origin controls CORS consistently. |

## Client Connection Recommendation

For WorkBuddy and other MCP clients behind Cloudflare Access, prefer an `npx mcp-remote` stdio proxy instead of native `type: http` client configuration. The server still runs `MCP_TRANSPORT=streamable-http`; only the client-side adapter changes.

```json
{
  "mcpServers": {
    "kingdee_mcp": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@latest",
        "https://your-cloudflare-domain.example.com/mcp",
        "--transport",
        "http-only",
        "--header",
        "Authorization:${KINGDEE_MCP_AUTH_HEADER}",
        "--header",
        "CF-Access-Client-Id:${KINGDEE_CF_ACCESS_CLIENT_ID}",
        "--header",
        "CF-Access-Client-Secret:${KINGDEE_CF_ACCESS_CLIENT_SECRET}"
      ],
      "env": {
        "KINGDEE_MCP_AUTH_HEADER": "Bearer <kingdee-mcp-token>",
        "KINGDEE_CF_ACCESS_CLIENT_ID": "<cloudflare-access-client-id>",
        "KINGDEE_CF_ACCESS_CLIENT_SECRET": "<cloudflare-access-client-secret>"
      },
      "disabled": false
    }
  }
}
```

Keep the colon-adjacent header form such as `Authorization:${KINGDEE_MCP_AUTH_HEADER}` in `args`; the value in `env` may contain spaces. This avoids argument escaping issues in Windows MCP clients while still sending a valid `Authorization: Bearer ...` header.

Native `type: http` direct connections are an experimental fallback only. Use them only when the client has stable Streamable HTTP support, correctly forwards Cloudflare Access headers, and does not disconnect during batch tool calls.

## Concurrency Variables

| Variable | Required | Recommended value | Description |
| --- | --- | --- | --- |
| `MCP_MAX_CONCURRENT_TOOLS` | no | `8` | Maximum concurrent tool handlers in this process. Extra calls wait briefly. |
| `MCP_MAX_CONCURRENT_KINGDEE_REQUESTS` | no | `4` | Maximum concurrent outbound Kingdee WebAPI requests. Protects Kingdee and this host. |
| `MCP_TOOL_QUEUE_TIMEOUT_SECONDS` | no | `3` | Wait time for a tool slot before returning `server_busy`. |
| `MCP_TOOL_CALL_TIMEOUT_SECONDS` | no | `120` | Wall-clock timeout for one tool call. |
| `MCP_HTTP_REQUEST_QUEUE_SIZE` | no | `128` | TCP accept backlog for the local `ThreadingHTTPServer`. |

## Bearer Token Mapping

`MCP_TOKEN_CONFIG` must point to a JSON file with hashed tokens only:

```json
{
  "tokens": {
    "sha256:<token_hash>": {
      "operator": "zhangsan",
      "kingdee_username": "zhangsan",
      "enabled": true,
      "allowed_tools": ["read"]
    }
  }
}
```

- `operator` is the MCP caller identity for audit and troubleshooting.
- `kingdee_username` is the real Kingdee user passed to `LoginByAppSecret`.
- `allowed_tools` may contain profiles or explicit tool names. Common profiles are `read`, `full-read`, `write`, and `all`.
- Plaintext Bearer tokens must not be written to this file or logs.
- The lightweight gateway hot-reloads this file when it changes. Adding, disabling, or deleting a token does not require restarting `kingdee-mcp.service`.

Generate a read-only token with the repository script:

```bash
/public/KingdeeMCP/scripts/generate_token.sh --operator zhangsan --kingdee-username zhangsan --allow read
```

Common `--allow` examples:

```bash
# Core read-only tools, recommended for normal production users
/public/KingdeeMCP/scripts/generate_token.sh --operator zhangsan --kingdee-username zhangsan --allow read

# All read-only tools
/public/KingdeeMCP/scripts/generate_token.sh --operator lisi --kingdee-username lisi --allow full-read

# Write-capable token. The write profile already includes read tools.
/public/KingdeeMCP/scripts/generate_token.sh --operator wangwu --kingdee-username wangwu --allow write

# Explicit tools only; repeat --allow or use comma-separated values
/public/KingdeeMCP/scripts/generate_token.sh --operator zhaoliu --kingdee-username zhaoliu --allow kingdee_smoke_test --allow kingdee_query_purchase_orders
/public/KingdeeMCP/scripts/generate_token.sh --operator zhaoliu --kingdee-username zhaoliu --allow kingdee_smoke_test,kingdee_query_purchase_orders

# Complete catalog, trusted admins only
/public/KingdeeMCP/scripts/generate_token.sh --operator admin --kingdee-username admin --allow all

# Machine-readable JSON output
/public/KingdeeMCP/scripts/generate_token.sh --operator lisi --kingdee-username lisi --allow read --json
```

The script uses only Python standard library plus this repository's source tree. It does not require installing the `kingdee-mcp` package or activating `.venv`.

## Variables Not Used By The Lightweight Production Entrypoint

The lightweight production version does not read SQL probing, usage-log, or OAuth metadata variables below:

```text
MCP_JSON_RESPONSE
MCP_STATELESS_HTTP
MCP_AUTH_ISSUER_URL
MCP_RESOURCE_SERVER_URL
MCP_USAGE_LOG
MCP_USAGE_LOG_DIR
MCP_MAX_CONCURRENT_WRITE_TOOLS
MCP_MAX_CONCURRENT_DESTRUCTIVE_TOOLS
MCP_MAX_CONCURRENT_TOOLS_PER_OPERATOR
MCP_KINGDEE_QUEUE_TIMEOUT_SECONDS
MCP_RATE_LIMIT_GLOBAL_PER_MINUTE
MCP_RATE_LIMIT_PER_OPERATOR_PER_MINUTE
MCP_SQLSERVER_HOST
MCP_SQLSERVER_PORT
MCP_SQLSERVER_USER
MCP_SQLSERVER_PASSWORD
MCP_SQLSERVER_DATABASE
MCP_SQLSERVER_SCHEMA
MCP_SQLSERVER_DRIVER
```

Keep those out of `.env` unless the corresponding optional feature is intentionally implemented.
