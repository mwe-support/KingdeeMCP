# Permission Architecture

The current production identity model is Bearer Token -> Kingdee user mapping.

## Principles

1. Kingdee remains the source of ERP permissions.
2. MCP Bearer tokens identify the caller and select the Kingdee user.
3. AI clients cannot pass `kingdee_username` as a tool argument.
4. The first lightweight production version exposes read-only tools only.
5. High-risk write/audit/delete/push flows are intentionally not registered yet.

## Current Flow

```text
Client request
  -> Cloudflare Access protection when enabled
  -> Authorization: Bearer <token>
  -> token hash lookup in MCP_TOKEN_CONFIG
  -> OperatorContext(operator, kingdee_username, allowed_tools)
  -> tool permission check
  -> LoginByAppSecret(acct_id, kingdee_username, app_id, app_secret, lcid)
  -> Kingdee WebAPI enforces that user's ERP permissions
```

## Token Mapping

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

- `operator` is the MCP-side identity.
- `kingdee_username` is the Kingdee WebAPI login user.
- `allowed_tools=["read"]` exposes the first-version read-only profile.

## Not In Current Production

The earlier `KINGDEE_REQUEST_USER` / header-injection idea is not used by the lightweight implementation. Do not document or deploy it as the current path unless a future Kingdee-supported delegation mode is verified.

Write-operation approval, SSO identity brokering, and parameter-sensitive risk rules remain future design topics.
