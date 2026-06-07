# Lightweight HTTP and Multi-User Auth Design

Status: implemented for first lightweight production version.

This document supersedes the earlier FastMCP Streamable HTTP plan. Production now uses `mcp_lite.py`, not FastMCP, Starlette, uvicorn, SSE, or MCP session headers.

## Runtime Flow

```text
AI client
  -> Cloudflare Access validates edge access when enabled
  -> POST /mcp with Authorization: Bearer <token>
  -> KingdeeMCP hashes the token and loads OperatorContext
  -> tools/list filters tools by allowed_tools
  -> tools/call checks tool permission before Kingdee WebAPI
  -> Kingdee session manager gets session for kingdee_username
  -> LoginByAppSecret if missing/expired
  -> Kingdee WebAPI call with kdservice-sessionid cookie
  -> ordinary JSON-RPC response with Content-Length
```

## Transport Variables

```text
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8199
MCP_PATH=/mcp
MCP_TOKEN_CONFIG=/public/KingdeeMCP/secrets/tokens.json
MCP_AUTH_DISABLED=false
```

`MCP_HOST=127.0.0.1` is a security requirement for this deployment. Use Cloudflare Tunnel/Access for remote access.

## Stdio Mode

Local stdio uses the same dispatcher and MCP content-length framing. It may use `KINGDEE_USERNAME` as the local Kingdee user.

```text
MCP_TRANSPORT=stdio
KINGDEE_USERNAME=<single-test-user>
```

Do not use stdio fallback for shared remote deployment.

## Token Mapping

`MCP_TOKEN_CONFIG` contains SHA-256 token hashes only:

```json
{
  "tokens": {
    "sha256:<hash>": {
      "operator": "zhangsan",
      "kingdee_username": "zhangsan",
      "enabled": true,
      "allowed_tools": ["read"]
    }
  }
}
```

`read` currently exposes only the 14 core read-only tools.

## Non-Goals In First Version

- Write/audit/delete/push tools.
- SQL Server probing.
- OAuth discovery metadata.
- FastMCP legacy compatibility in production.
- Usage-log report tools.
