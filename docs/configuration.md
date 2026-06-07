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

## Required MCP Transport Variables

| Variable | Required | Recommended value | Description |
| --- | --- | --- | --- |
| `MCP_TRANSPORT` | yes | `streamable-http` | Runs the lightweight HTTP gateway. Use `stdio` only for local client tests. |
| `MCP_HOST` | yes | `127.0.0.1` | Local bind address. Keep localhost-only for security. |
| `MCP_PORT` | yes | `8199` | Local MCP origin port used by systemd and cloudflared. |
| `MCP_PATH` | yes | `/mcp` | JSON-RPC MCP endpoint path. |
| `MCP_TOKEN_CONFIG` | yes for HTTP production | `/public/KingdeeMCP/secrets/tokens.json` | JSON file containing SHA-256 token hashes and Kingdee user mapping. |
| `MCP_AUTH_DISABLED` | no | `false` | Set `true` only for local unauthenticated tests. Never enable in shared production. |

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
- `allowed_tools` may contain `read` for the first lightweight production profile.
- Plaintext Bearer tokens must not be written to this file or logs.

## Variables Not Used By The Lightweight Production Entrypoint

The first lightweight production version does not use the legacy FastMCP, SQL probing, write-tool, usage-log, or OAuth metadata variables below:

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

Keep those out of `.env` unless the corresponding legacy or optional feature is intentionally reintroduced.
