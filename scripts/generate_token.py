#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kingdee_mcp.token_cli import DEFAULT_TOKEN_BYTES, command_create  # noqa: E402


def read_env_file_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    prefix = name + "="
    export_prefix = "export " + prefix
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(export_prefix):
            value = line[len(export_prefix) :]
        elif line.startswith(prefix):
            value = line[len(prefix) :]
        else:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def default_config_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.getenv("MCP_TOKEN_CONFIG"):
        return os.environ["MCP_TOKEN_CONFIG"]
    env_value = read_env_file_value(REPO_DIR / ".env", "MCP_TOKEN_CONFIG")
    if env_value:
        return env_value
    return str(REPO_DIR / "secrets" / "tokens.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_token.py",
        description="Generate a KingdeeMCP Bearer token and update the hashed token mapping.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Read-only token for the 14 core read tools
  cd /public/KingdeeMCP
  /public/KingdeeMCP/scripts/generate_token.sh --operator zhangsan --kingdee-username zhangsan --allow read

  # Full read-only token for every read-only tool in the catalog
  /public/KingdeeMCP/scripts/generate_token.sh --operator lisi --kingdee-username lisi --allow full-read

  # Write-capable token. The write profile already includes read tools.
  /public/KingdeeMCP/scripts/generate_token.sh --operator wangwu --kingdee-username wangwu --allow write

  # Allow explicit tools only. Repeat --allow or use comma-separated values.
  /public/KingdeeMCP/scripts/generate_token.sh --operator zhaoliu --kingdee-username zhaoliu --allow kingdee_smoke_test --allow kingdee_query_purchase_orders
  /public/KingdeeMCP/scripts/generate_token.sh --operator zhaoliu --kingdee-username zhaoliu --allow kingdee_smoke_test,kingdee_query_purchase_orders

  # Complete catalog token for trusted admins only
  /public/KingdeeMCP/scripts/generate_token.sh --operator admin --kingdee-username admin --allow all

  # Print machine-readable JSON output
  /public/KingdeeMCP/scripts/generate_token.sh --operator lisi --kingdee-username lisi --allow read --json
""",
    )
    parser.add_argument("--operator", required=True, help="MCP audit identity")
    parser.add_argument("--kingdee-username", required=True, help="Kingdee username used by LoginByAppSecret")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help=(
            "allowed profile or explicit tool name; profiles: "
            "read/core=14 core read tools, full-read/read-all=all read-only tools, "
            "write=read and write tools, ops=ops placeholders, all/high/*=complete catalog; "
            "save and audit are accepted as write aliases; can repeat or use comma list; default: read"
        ),
    )
    parser.add_argument("--config", help="path to tokens.json; default: MCP_TOKEN_CONFIG, .env, then repo secrets/tokens.json")
    parser.add_argument("--token", help="use a provided token instead of generating one; mainly for controlled rotation/tests")
    parser.add_argument("--bytes", type=int, default=DEFAULT_TOKEN_BYTES, help="random bytes for generated token, default 32")
    parser.add_argument("--disabled", action="store_true", help="create mapping with enabled=false")
    parser.add_argument("--force", action="store_true", help="overwrite existing hash in config")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.config = default_config_path(args.config)
    args.allow = args.allow or ["read"]
    try:
        return command_create(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
