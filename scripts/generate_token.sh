#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -n "${PYTHON:-}" ]]; then
  exec "$PYTHON" "$SCRIPT_DIR/generate_token.py" "$@"
fi

if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
  exec "$REPO_DIR/.venv/bin/python" "$SCRIPT_DIR/generate_token.py" "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT_DIR/generate_token.py" "$@"
fi

if command -v python >/dev/null 2>&1; then
  exec python "$SCRIPT_DIR/generate_token.py" "$@"
fi

echo "error: python3 or python is required to generate KingdeeMCP tokens" >&2
exit 127
