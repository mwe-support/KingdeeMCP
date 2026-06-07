#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/public/KingdeeMCP}"
SERVICE_NAME="${SERVICE_NAME:-kingdee-mcp.service}"
UNIT_SRC="$REPO_DIR/deploy/systemd/$SERVICE_NAME"
UNIT_DST="/etc/systemd/system/$SERVICE_NAME"

if [[ $EUID -ne 0 ]]; then
  echo "error: run as root" >&2
  exit 1
fi

if [[ ! -f "$REPO_DIR/.env" ]]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  chmod 600 "$REPO_DIR/.env"
  echo "created $REPO_DIR/.env; fill it before starting the service"
fi

mkdir -p "$REPO_DIR/secrets" "$REPO_DIR/logs"
if [[ ! -f "$REPO_DIR/secrets/tokens.json" ]]; then
  printf '{\n  "tokens": {}\n}\n' > "$REPO_DIR/secrets/tokens.json"
  chmod 600 "$REPO_DIR/secrets/tokens.json"
fi

install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload

echo "installed $UNIT_DST"
echo "next: edit $REPO_DIR/.env; keep MCP_HOST=127.0.0.1 and MCP_PORT=8199"
echo "token: generate read-only tokens with kingdee-mcp-token create --allow read --config $REPO_DIR/secrets/tokens.json"
echo "docs: see $REPO_DIR/docs/configuration.md"
echo "start: systemctl start $SERVICE_NAME"
echo "enable: systemctl enable $SERVICE_NAME"