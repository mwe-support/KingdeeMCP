import json
import os

from kingdee_mcp.auth import hash_bearer_token
from kingdee_mcp.token_cli import build_token_entry, generate_bearer_token, main, parse_allowed_tools


def test_generate_bearer_token_is_random_and_long():
    first = generate_bearer_token()
    second = generate_bearer_token()

    assert first != second
    assert len(first) >= 32


def test_parse_allowed_tools_supports_repeat_comma_and_legacy_aliases():
    assert parse_allowed_tools(["read,save", "audit", "read"]) == ["read", "write"]


def test_build_token_entry_rejects_conflicting_profiles():
    entry = build_token_entry(
        operator="zhangsan",
        kingdee_username="KD_ZHANGSAN",
        allowed_tools=["read", "kingdee_query_operation_logs"],
    )
    assert entry["allowed_tools"] == ["read", "kingdee_query_operation_logs"]

    try:
        build_token_entry(
            operator="zhangsan",
            kingdee_username="KD_ZHANGSAN",
            allowed_tools=["read,write"],
        )
    except ValueError as exc:
        assert "write" in str(exc)
    else:
        raise AssertionError("conflicting read/write profiles should fail")

    try:
        build_token_entry(
            operator="zhangsan",
            kingdee_username="KD_ZHANGSAN",
            allowed_tools=["all,kingdee_query_bills"],
        )
    except ValueError as exc:
        assert "all" in str(exc)
    else:
        raise AssertionError("all plus explicit tool should fail")


def test_token_cli_create_updates_config_without_plaintext_token(tmp_path, capsys):
    config_path = tmp_path / "tokens.json"
    token = "known-token-for-test"

    result = main([
        "create",
        "--operator",
        "zhangsan",
        "--kingdee-username",
        "KD_ZHANGSAN",
        "--allow",
        "read,kingdee_query_operation_logs",
        "--config",
        str(config_path),
        "--token",
        token,
    ])

    assert result == 0
    output = capsys.readouterr().out
    assert token in output
    data = json.loads(config_path.read_text(encoding="utf-8"))
    token_hash = hash_bearer_token(token)
    assert token_hash in data["tokens"]
    assert token not in config_path.read_text(encoding="utf-8")
    assert data["tokens"][token_hash] == {
        "operator": "zhangsan",
        "kingdee_username": "KD_ZHANGSAN",
        "enabled": True,
        "allowed_tools": ["read", "kingdee_query_operation_logs"],
    }
    assert oct(os.stat(config_path).st_mode & 0o777) == "0o600"


def test_token_cli_hash_command(capsys):
    result = main(["hash", "--token", "abc"])

    assert result == 0
    assert capsys.readouterr().out.strip() == hash_bearer_token("abc")