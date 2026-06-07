from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # Legacy FastMCP compatibility only; production lightweight gateway does not require mcp.
    from mcp.server.auth.middleware.auth_context import get_access_token as _mcp_get_access_token
    from mcp.server.auth.provider import AccessToken, TokenVerifier
except Exception:  # pragma: no cover - exercised in minimal production installs without mcp.
    _mcp_get_access_token = None

    @dataclass(frozen=True)
    class AccessToken:  # type: ignore[no-redef]
        token: str
        client_id: str
        scopes: list[str]
        subject: str
        claims: dict[str, Any]

    class TokenVerifier:  # type: ignore[no-redef]
        pass


@dataclass(frozen=True)
class OperatorContext:
    operator: str
    kingdee_username: str
    allowed_tools: frozenset[str]
    enabled: bool = True


@dataclass(frozen=True)
class TokenRecord:
    token_hash: str
    operator: str
    kingdee_username: str
    enabled: bool
    allowed_tools: frozenset[str]


class AuthError(RuntimeError):
    pass


def hash_bearer_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_token_records(path: str) -> dict[str, TokenRecord]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records: dict[str, TokenRecord] = {}
    for token_hash, raw in data.get("tokens", {}).items():
        if not token_hash.startswith("sha256:"):
            raise ValueError(f"token hash must start with sha256:: {token_hash}")
        operator = str(raw.get("operator") or "").strip()
        kingdee_username = str(raw.get("kingdee_username") or "").strip()
        if not operator or not kingdee_username:
            raise ValueError(f"token mapping {token_hash} must include operator and kingdee_username")
        allowed_tools = frozenset(str(x).strip() for x in raw.get("allowed_tools", []) if str(x).strip())
        records[token_hash] = TokenRecord(
            token_hash=token_hash,
            operator=operator,
            kingdee_username=kingdee_username,
            enabled=bool(raw.get("enabled", True)),
            allowed_tools=allowed_tools,
        )
    return records


def match_bearer_token(records: dict[str, TokenRecord], token: str) -> TokenRecord | None:
    token_hash = hash_bearer_token(token)
    for configured_hash, record in records.items():
        if hmac.compare_digest(configured_hash, token_hash):
            return record if record.enabled else None
    return None


def context_from_token_record(record: TokenRecord) -> OperatorContext:
    return OperatorContext(
        operator=record.operator,
        kingdee_username=record.kingdee_username,
        allowed_tools=record.allowed_tools,
        enabled=record.enabled,
    )


def authenticate_authorization_header(records: dict[str, TokenRecord], authorization: str) -> OperatorContext | None:
    normalized = str(authorization or "").strip()
    if not normalized.startswith("Bearer "):
        return None
    token = normalized[len("Bearer ") :].strip()
    if not token:
        return None
    record = match_bearer_token(records, token)
    return context_from_token_record(record) if record else None


class MappingTokenVerifier(TokenVerifier):
    def __init__(self, records: dict[str, TokenRecord]):
        self._records = records

    @classmethod
    def from_file(cls, path: str) -> "MappingTokenVerifier":
        return cls(load_token_records(path))

    async def verify_token(self, token: str):
        record = match_bearer_token(self._records, token)
        if record is None:
            return None
        return AccessToken(
            token=record.token_hash,
            client_id=record.operator,
            scopes=sorted(record.allowed_tools),
            subject=record.kingdee_username,
            claims={
                "operator": record.operator,
                "kingdee_username": record.kingdee_username,
                "allowed_tools": sorted(record.allowed_tools),
            },
        )


def operator_context_from_access_token(access_token: Any) -> OperatorContext:
    claims: dict[str, Any] = access_token.claims or {}
    operator = str(claims.get("operator") or access_token.client_id or "").strip()
    kingdee_username = str(claims.get("kingdee_username") or access_token.subject or "").strip()
    allowed_tools = frozenset(str(x).strip() for x in (claims.get("allowed_tools") or access_token.scopes or []) if str(x).strip())
    if not operator or not kingdee_username:
        raise AuthError("authenticated token is missing operator or kingdee_username")
    return OperatorContext(operator=operator, kingdee_username=kingdee_username, allowed_tools=allowed_tools)


def local_operator_context(default_kingdee_username: str) -> OperatorContext:
    username = (default_kingdee_username or "").strip()
    if not username:
        raise AuthError("KINGDEE_USERNAME is required for local stdio mode or unauthenticated calls")
    return OperatorContext(operator="local-stdio", kingdee_username=username, allowed_tools=frozenset({"read", "write", "high"}))


def current_operator_context(default_kingdee_username: str = "") -> OperatorContext:
    if _mcp_get_access_token is not None:
        access_token = _mcp_get_access_token()
        if access_token is not None:
            return operator_context_from_access_token(access_token)
    return local_operator_context(default_kingdee_username)
