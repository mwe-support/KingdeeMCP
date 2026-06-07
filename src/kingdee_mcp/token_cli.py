from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Sequence

from .auth import hash_bearer_token


DEFAULT_TOKEN_BYTES = 32
PROFILE_SCOPES = frozenset({"read", "write", "core", "high", "all", "*"})
DEPRECATED_PROFILE_ALIASES = {
    "save": "write",
    "audit": "write",
}



def generate_bearer_token(nbytes: int = DEFAULT_TOKEN_BYTES) -> str:
    if nbytes < 24:
        raise ValueError("token bytes must be at least 24")
    return secrets.token_urlsafe(nbytes)


def normalize_allowed_tool(item: str) -> str:
    item = item.strip()
    if item in DEPRECATED_PROFILE_ALIASES:
        return DEPRECATED_PROFILE_ALIASES[item]
    return item


def parse_allowed_tools(values: Sequence[str]) -> list[str]:
    tools: list[str] = []
    for value in values:
        for item in value.split(","):
            item = normalize_allowed_tool(item)
            if item and item not in tools:
                tools.append(item)
    return tools


def validate_allowed_tools(tools: Sequence[str]) -> None:
    if "*" in tools and len(tools) > 1:
        raise ValueError("'*' grants the full catalog and cannot be combined with other allow values")
    if "all" in tools and len(tools) > 1:
        raise ValueError("'all' grants the full catalog and cannot be combined with other allow values")
    if "high" in tools and any(item in {"read", "write", "core"} for item in tools):
        raise ValueError("'high' already grants the full catalog; do not combine it with read/write/core")
    if "read" in tools and "write" in tools:
        raise ValueError("'write' already includes the core read tools; use write only")
    if "core" in tools and any(item in {"read", "write"} for item in tools):
        raise ValueError("'core' overlaps read/write; use one profile plus optional explicit tool names")


def build_token_entry(
    *,
    operator: str,
    kingdee_username: str,
    allowed_tools: Sequence[str],
    enabled: bool = True,
) -> dict:
    operator = operator.strip()
    kingdee_username = kingdee_username.strip()
    if not operator:
        raise ValueError("operator is required")
    if not kingdee_username:
        raise ValueError("kingdee_username is required")
    tools = parse_allowed_tools(allowed_tools)
    if not tools:
        raise ValueError("at least one allowed profile or explicit tool name is required")
    validate_allowed_tools(tools)
    return {
        "operator": operator,
        "kingdee_username": kingdee_username,
        "enabled": enabled,
        "allowed_tools": tools,
    }


def load_token_config(path: Path) -> dict:
    if not path.exists():
        return {"tokens": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("token config must be a JSON object")
    tokens = data.setdefault("tokens", {})
    if not isinstance(tokens, dict):
        raise ValueError("token config field 'tokens' must be an object")
    return data


def save_token_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not existed:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def add_token_to_config(path: Path, token_hash: str, entry: dict, *, force: bool = False) -> None:
    data = load_token_config(path)
    tokens = data["tokens"]
    if token_hash in tokens and not force:
        raise ValueError(f"token hash already exists in {path}; use --force to overwrite")
    tokens[token_hash] = entry
    save_token_config(path, data)


def command_create(args: argparse.Namespace) -> int:
    token = args.token or generate_bearer_token(args.bytes)
    token_hash = hash_bearer_token(token)
    entry = build_token_entry(
        operator=args.operator,
        kingdee_username=args.kingdee_username,
        allowed_tools=args.allow,
        enabled=not args.disabled,
    )

    if args.config:
        add_token_to_config(Path(args.config), token_hash, entry, force=args.force)

    output = {
        "bearer_token": token,
        "token_hash": token_hash,
        "config_entry": {token_hash: entry},
        "config_updated": bool(args.config),
        "config_path": args.config or "",
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("Bearer token: " + token)
        print("Config hash: " + token_hash)
        if args.config:
            print("Config updated: " + args.config)
        else:
            print("Config entry:")
            print(json.dumps({token_hash: entry}, ensure_ascii=False, indent=2))
        print("Save the bearer token now. It is not stored in the config file.")
    return 0


def command_hash(args: argparse.Namespace) -> int:
    token = args.token
    if args.stdin:
        token = sys.stdin.read().strip()
    if not token:
        raise ValueError("provide --token or --stdin")
    print(hash_bearer_token(token))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kingdee-mcp-token", description="Manage KingdeeMCP Bearer Tokens")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a bearer token and optional token config entry")
    create.add_argument("--operator", required=True, help="MCP audit identity")
    create.add_argument("--kingdee-username", required=True, help="Kingdee username used by LoginByAppSecret")
    create.add_argument(
        "--allow",
        action="append",
        default=[],
        help=(
            "allowed profile or explicit tool name; current lightweight production profile: "
            "read=14 read-only tools. Legacy profile names are accepted for compatibility "
            "but do not expose write tools in the lightweight production entrypoint; "
            "can repeat or use comma list"
        ),
    )
    create.add_argument("--config", help="path to tokens.json to update")
    create.add_argument("--token", help="use a provided token instead of generating one; mainly for controlled rotation/tests")
    create.add_argument("--bytes", type=int, default=DEFAULT_TOKEN_BYTES, help="random bytes for generated token, default 32")
    create.add_argument("--disabled", action="store_true", help="create mapping with enabled=false")
    create.add_argument("--force", action="store_true", help="overwrite existing hash in config")
    create.add_argument("--json", action="store_true", help="print machine-readable JSON")
    create.set_defaults(func=command_create)

    hash_cmd = sub.add_parser("hash", help="hash an existing bearer token")
    hash_cmd.add_argument("--token", help="token to hash")
    hash_cmd.add_argument("--stdin", action="store_true", help="read token from stdin")
    hash_cmd.set_defaults(func=command_hash)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())