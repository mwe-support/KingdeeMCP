import json

import pytest

from kingdee_mcp.auth import authenticate_authorization_header, hash_bearer_token, load_token_records


def test_authenticate_authorization_header_returns_operator_context(tmp_path):
    token = "dev-token"
    config = {
        "tokens": {
            hash_bearer_token(token): {
                "operator": "zhangsan",
                "kingdee_username": "KD_ZHANGSAN",
                "enabled": True,
                "allowed_tools": ["read", "save"],
            }
        }
    }
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    records = load_token_records(str(path))
    context = authenticate_authorization_header(records, f"Bearer {token}")

    assert context is not None
    assert context.operator == "zhangsan"
    assert context.kingdee_username == "KD_ZHANGSAN"
    assert context.allowed_tools == frozenset({"read", "save"})


def test_authenticate_authorization_header_rejects_disabled_token(tmp_path):
    token = "disabled-token"
    config = {
        "tokens": {
            hash_bearer_token(token): {
                "operator": "lisi",
                "kingdee_username": "KD_LISI",
                "enabled": False,
                "allowed_tools": ["read"],
            }
        }
    }
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    records = load_token_records(str(path))

    assert authenticate_authorization_header(records, f"Bearer {token}") is None


def test_token_config_requires_operator_and_kingdee_username(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps({"tokens": {hash_bearer_token("bad"): {"operator": "missing-user"}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_token_records(str(path))
