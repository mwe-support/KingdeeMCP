# Structured Access Logging

KingdeeMCP writes one UTF-8 JSON object for every tool call and every failed or
disconnected HTTP/MCP request. Successful health checks, initialization,
`ping`, `tools/list`, and GET connection probes are excluded to avoid
high-volume transport noise. The access log is separate from systemd journal
output so it can be filtered, archived, and removed without changing global journald retention.

## Production Configuration

```text
MCP_ACCESS_LOG_PATH=/var/log/kingdee-mcp/access.jsonl
MCP_ACCESS_LOG_RETENTION_DAYS=30
```

The systemd unit uses `LogsDirectory=kingdee-mcp` to create the log directory.
An empty `MCP_ACCESS_LOG_PATH` disables file access logging. Retention must be
between 1 and 30 days; values above 30 make service configuration validation
fail instead of silently retaining data longer than intended.

Logs rotate daily at 00:00 UTC. Archived files older than the configured
retention are deleted during startup and rollover.

## Event Schema

```json
{
  "timestamp": "2026-08-13T08:00:00.000Z",
  "event": "mcp_access",
  "request_id": "workbuddy-7f95c0",
  "user": "alice",
  "kingdee_username": "alice",
  "role": "read",
  "tool_name": "kingdee_query_inventory",
  "mcp_method": "tools/call",
  "duration_ms": 182.417,
  "response_bytes": 946,
  "status": "success",
  "http_status": 200,
  "error_type": null
}
```

- `user`: MCP token mapping's `operator`.
- `kingdee_username`: Kingdee identity used by `LoginByAppSecret`.
- `role`: normalized permission profile such as `read`, `full-read`,
  `write`, `ops`, `high`, `all`, or `custom`.
- `tool_name`: populated for normal `tools/call`; it may be null on
  malformed, authentication, transport, or other non-tool failures.
- `status`: `success`, `error`, or `client_disconnected`.
- `error_type`: protocol/tool error category without sensitive payload data.
- `request_id`: a safe incoming `X-Request-ID`, or a generated 32-character
  hexadecimal id. The response includes the same `X-Request-ID`.

The log deliberately excludes Authorization headers, Bearer tokens, AppSecret,
cookies, Kingdee session ids, tool arguments, and full business responses.

## Operations

Follow new tool calls:

```bash
tail -F /var/log/kingdee-mcp/access.jsonl
```

Show failed requests:

```bash
jq -c 'select(.status != "success")' /var/log/kingdee-mcp/access.jsonl
```

Aggregate failures by user and tool:

```bash
jq -r 'select(.status != "success") | [.user, .tool_name, .error_type] | @tsv' \
  /var/log/kingdee-mcp/access.jsonl | sort | uniq -c | sort -nr
```

Find one request across client and server logs:

```bash
jq -c 'select(.request_id == "workbuddy-7f95c0")' \
  /var/log/kingdee-mcp/access.jsonl
```

The regular systemd journal remains the place for startup failures and
unexpected internal exceptions:

```bash
journalctl -u kingdee-mcp.service --since "1 hour ago" --no-pager
```
