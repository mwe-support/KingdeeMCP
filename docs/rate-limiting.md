# Lightweight Rate Limiting Strategy

This deployment targets 10-20 MCP clients with short bursts around 100 concurrent incoming requests.
The lightweight gateway should absorb bursts and avoid forwarding them directly to Kingdee WebAPI.

## Current Variables

```text
MCP_MAX_CONCURRENT_TOOLS=8
MCP_MAX_CONCURRENT_KINGDEE_REQUESTS=4
MCP_TOOL_QUEUE_TIMEOUT_SECONDS=15
MCP_TOOL_CALL_TIMEOUT_SECONDS=120
MCP_HTTP_REQUEST_QUEUE_SIZE=128
```

## Behavior

- At most 8 MCP tool calls run at the same time in this process.
- At most 4 outbound Kingdee WebAPI requests run at the same time.
- Extra tool calls wait up to `MCP_TOOL_QUEUE_TIMEOUT_SECONDS` for a slot.
- Calls that cannot get a slot return a structured `server_busy` tool error.
- One tool call is bounded by `MCP_TOOL_CALL_TIMEOUT_SECONDS`.
- The local HTTP server backlog is controlled by `MCP_HTTP_REQUEST_QUEUE_SIZE`.

## Rationale

The HTTP layer is intentionally stdlib and lightweight. The real bottlenecks are Kingdee WebAPI latency, response size, and the server memory cap.

A 100-request burst should degrade like this:

```text
100 incoming requests
  -> local HTTP backlog accepts a short burst
  -> up to 8 active MCP tool handlers
  -> up to 4 active Kingdee WebAPI calls
  -> remaining calls briefly wait
  -> calls that cannot get a slot quickly return server_busy
```

Do not raise these defaults until load testing confirms Kingdee WebAPI, clients, and this host are stable.

## Conservative Tuning

For safer operation on a smaller host:

```text
MCP_MAX_CONCURRENT_TOOLS=4
MCP_MAX_CONCURRENT_KINGDEE_REQUESTS=2
MCP_TOOL_QUEUE_TIMEOUT_SECONDS=15
```

For a larger host after successful load testing:

```text
MCP_MAX_CONCURRENT_TOOLS=12
MCP_MAX_CONCURRENT_KINGDEE_REQUESTS=6
MCP_HTTP_REQUEST_QUEUE_SIZE=256
```

Do not exceed `MCP_MAX_CONCURRENT_KINGDEE_REQUESTS=8` on the current host without measuring Kingdee response latency and memory usage.
