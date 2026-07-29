from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .auth import hash_bearer_token


DEFAULT_TOKEN_BYTES = 32
PROFILE_SCOPES = frozenset({"read", "core", "full-read", "read-all", "write", "ops", "high", "all", "*"})
PROFILE_ALIASES = {
    "save": "write",
    "audit": "write",
}



def generate_bearer_token(nbytes: int = DEFAULT_TOKEN_BYTES) -> str:
    if nbytes < 24:
        raise ValueError("token bytes must be at least 24")
    return secrets.token_urlsafe(nbytes)


def normalize_allowed_tool(item: str) -> str:
    item = item.strip()
    if item in PROFILE_ALIASES:
        return PROFILE_ALIASES[item]
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
    profiles = set(tools).intersection(PROFILE_SCOPES)
    if len(profiles) > 1:
        profile_list = ", ".join(sorted(profiles))
        raise ValueError(f"conflicting permission profiles: {profile_list}; use one profile plus optional explicit tool names")


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
    mode = stat.S_IRUSR | stat.S_IWUSR
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
        os.chmod(path, mode)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


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
        allowed_tools=args.allow or ["read"],
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
            "allowed profile or explicit tool name; profiles: "
            "read/core=14 core read tools, full-read/read-all=all read-only tools including experiments, "
            "write=stable read and write tools, ops=ops placeholders, "
            "all/high/*=complete stable catalog excluding experiments; "
            "save and audit are accepted as write aliases; "
            "one profile may be combined with explicit tool names; can repeat or use comma list"
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
