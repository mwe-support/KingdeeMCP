import json

import pytest

from kingdee_mcp.auth import MappingTokenVerifier, hash_bearer_token, load_token_records


@pytest.mark.asyncio
async def test_mapping_token_verifier_returns_operator_claims(tmp_path):
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

    verifier = MappingTokenVerifier.from_file(str(path))
    access_token = await verifier.verify_token(token)

    assert access_token is not None
    assert access_token.token == hash_bearer_token(token)
    assert access_token.client_id == "zhangsan"
    assert access_token.subject == "KD_ZHANGSAN"
    assert access_token.claims["kingdee_username"] == "KD_ZHANGSAN"
    assert access_token.claims["allowed_tools"] == ["read", "save"]


@pytest.mark.asyncio
async def test_mapping_token_verifier_rejects_disabled_token(tmp_path):
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

    verifier = MappingTokenVerifier.from_file(str(path))

    assert await verifier.verify_token(token) is None


def test_token_config_requires_operator_and_kingdee_username(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps({"tokens": {hash_bearer_token("bad"): {"operator": "missing-user"}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_token_records(str(path))
