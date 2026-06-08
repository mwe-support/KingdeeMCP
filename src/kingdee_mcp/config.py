from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


TransportName = Literal["stdio", "sse", "streamable-http"]


@dataclass(frozen=True)
class ServiceConfig:
    server_url: str
    acct_id: str
    app_id: str
    app_secret: str
    lcid: int
    default_username: str = ""
    session_ttl_seconds: float = 1200.0


@dataclass(frozen=True)
class TransportConfig:
    transport: TransportName
    host: str
    port: int
    path: str
    token_config: str
    auth_disabled: bool
    issuer_url: str
    resource_server_url: str
    json_response: bool
    stateless_http: bool
    cors_allow_origins: tuple[str, ...] = ("*",)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def load_service_config() -> ServiceConfig:
    return ServiceConfig(
        server_url=os.getenv("KINGDEE_SERVER_URL", "http://your-server/k3cloud/"),
        acct_id=os.getenv("KINGDEE_ACCT_ID", ""),
        app_id=os.getenv("KINGDEE_APP_ID", ""),
        app_secret=os.getenv("KINGDEE_APP_SEC", ""),
        lcid=int(os.getenv("KINGDEE_LCID", "2052")),
        default_username=os.getenv("KINGDEE_USERNAME", ""),
        session_ttl_seconds=_float_env("KINGDEE_SESSION_TTL_SECONDS", 1200.0),
    )


def load_transport_config() -> TransportConfig:
    raw_transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower().replace("_", "-")
    if raw_transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("MCP_TRANSPORT must be one of: stdio, sse, streamable-http")

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8199"))
    path = os.getenv("MCP_PATH", "/mcp")
    if not path.startswith("/"):
        path = "/" + path

    resource_server_url = os.getenv("MCP_RESOURCE_SERVER_URL", f"http://{host}:{port}{path}")
    issuer_url = os.getenv("MCP_AUTH_ISSUER_URL", resource_server_url)
    cors_allow_origins = tuple(
        item.strip()
        for item in os.getenv("MCP_CORS_ALLOW_ORIGINS", "*").split(",")
        if item.strip()
    )

    return TransportConfig(
        transport=raw_transport,  # type: ignore[arg-type]
        host=host,
        port=port,
        path=path,
        token_config=os.getenv("MCP_TOKEN_CONFIG", ""),
        auth_disabled=_bool_env("MCP_AUTH_DISABLED", False),
        issuer_url=issuer_url,
        resource_server_url=resource_server_url,
        json_response=_bool_env("MCP_JSON_RESPONSE", False),
        stateless_http=_bool_env("MCP_STATELESS_HTTP", False),
        cors_allow_origins=cors_allow_origins,
    )
