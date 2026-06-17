# Cloudflared Docker Compose deployment

This deployment runs the `kingdee-mcp` Cloudflare Tunnel connector as a Docker Compose service with the official Cloudflare image via the same registry mirror style used by the Lingxing deployment.
The MCP origin service still listens only on `127.0.0.1:8199`; the connector uses host networking so it can reach that local-only origin without publishing the MCP port.

## Tunnel token

The tunnel token is expected at:

```bash
/etc/cloudflared/kingdee-mcp.token
```

Keep this file owned by root with mode `600`:

```bash
sudo install -d -m 700 /etc/cloudflared
sudo install -m 600 /path/to/kingdee-mcp.token /etc/cloudflared/kingdee-mcp.token
```

The compose file mounts the token as read-only and uses `--token-file`, so the secret does not appear in `docker inspect` command arguments.
The container runs as root only to read the `600 root:root` token file; the MCP origin remains bound to localhost and is not published by Docker.

## Start

```bash
docker compose -f /public/KingdeeMCP/deploy/cloudflared/compose.yml pull
docker compose -f /public/KingdeeMCP/deploy/cloudflared/compose.yml up -d
```

## Check

```bash
docker compose -f /public/KingdeeMCP/deploy/cloudflared/compose.yml ps
docker compose -f /public/KingdeeMCP/deploy/cloudflared/compose.yml logs --tail=100 -f
```

## Stop

```bash
docker compose -f /public/KingdeeMCP/deploy/cloudflared/compose.yml down
```

Do not run this compose connector and the host `cloudflared.service` connector at the same time for the same tunnel.

## Cloudflare Tunnel ingress

Keep the remote tunnel ingress minimal:

```yaml
ingress:
  - hostname: kingdee.nakroyn8n.top
    service: http://127.0.0.1:8199
  - service: http_status:404
warp-routing:
  enabled: false
```

Do not add `originRequest.access` with `required: false` or a custom `httpHostHeader`; they do not improve security for this local origin and make troubleshooting harder.

## Cloudflare Access

Use one Cloudflare Access self-hosted application for the MCP hostname and one Service Auth policy that includes the `kingdee-mcp-client` service token.
Kingdee user identity and tool permissions are still controlled by KingdeeMCP Bearer tokens, not by Cloudflare service tokens.

Requests through Cloudflare Access need these headers:

```text
CF-Access-Client-Id: <cloudflare access client id>
CF-Access-Client-Secret: <cloudflare access client secret>
Authorization: Bearer <kingdee mcp bearer token>
```

Optional header when the zone has browser-oriented checks that affect API clients:

```text
User-Agent: KingdeeMCP-Client/1.0
```

For browser or WebView MCP clients, enable `options_preflight_bypass` on the Cloudflare Access application and leave Access-level `cors_headers` unset. This lets unauthenticated `OPTIONS` preflight requests reach the lightweight MCP origin, which returns CORS headers from `MCP_CORS_ALLOW_ORIGINS`. Authenticated `POST` requests still require both Cloudflare Service Auth headers and the MCP Bearer token.

## Image

The compose file uses:

```yaml
image: docker.m.daocloud.io/cloudflare/cloudflared:2026.5.2
```

This is a registry mirror for the official `cloudflare/cloudflared` image and avoids Docker Hub timeout on the current server.
If Docker Hub is stable in another environment, the image field can be changed to `cloudflare/cloudflared:2026.5.2`.
## Protocol

This deployment pins `cloudflared` to `--protocol http2` for better stability when clients connect through unstable cross-border networks. HTTP/2 uses TCP/TLS and is preferred here over default QUIC/UDP for WorkBuddy batch MCP calls.
