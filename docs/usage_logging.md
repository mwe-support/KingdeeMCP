# Usage Logging Notes

Status: legacy reference.

The current lightweight production entrypoint does not register usage-log MCP tools and does not read `MCP_USAGE_LOG` or `MCP_USAGE_LOG_DIR`.

The old FastMCP `server.py` contained an in-process usage logging/reporting system. Keep that code as legacy reference only unless usage logging is intentionally reintroduced for the lightweight gateway.

If logging is reintroduced, prefer structured records that include:

- `operator`
- `kingdee_username`
- `tool_name`
- `form_id` when available
- duration and success/error class
- sanitized argument keys only

Never log:

- Bearer token plaintext
- token hash mapping file content
- `KINGDEE_APP_SEC`
- `KDSVCSessionId` or `kdservice-sessionid`
- Cloudflare Access client secret
- full sensitive bill payloads
