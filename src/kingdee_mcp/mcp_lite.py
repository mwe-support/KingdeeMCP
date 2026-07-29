from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .auth import AuthError, OperatorContext, authenticate_authorization_header, load_token_records, local_operator_context
from .config import ServiceConfig, TransportConfig, load_service_config, load_transport_config
from .kingdee_client import KingdeeWebAPIClient
from .light_tools import (
    ALL_LIGHTWEIGHT_TOOL_NAMES,
    ALL_READ_TOOL_NAMES,
    CORE_READ_TOOL_NAMES,
    EXPERIMENTAL_READ_TOOL_NAMES,
    MIGRATED_OPS_TOOL_NAMES,
    MIGRATED_WRITE_TOOL_NAMES,
    ToolDefinition,
    build_core_read_tools,
)

SERVER_NAME = "kingdee-mcp-lite"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2025-03-26"


class KingdeeThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = int(os.getenv("MCP_HTTP_REQUEST_QUEUE_SIZE", "128") or "128")


class AsyncLoopRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="kingdee-mcp-async", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro, *, timeout: float | None = None) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            raise

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


@dataclass
class AuthConfig:
    token_config: str
    auth_disabled: bool
    default_kingdee_username: str
    records: dict[str, Any]
    fingerprint: tuple[int, int, int, int] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def load(cls, transport: TransportConfig, service: ServiceConfig) -> "AuthConfig":
        records: dict[str, Any] = {}
        fingerprint: tuple[int, int, int, int] | None = None
        if transport.token_config and not transport.auth_disabled:
            records = load_token_records(transport.token_config)
            fingerprint = cls._fingerprint_for_path(transport.token_config)
        return cls(
            token_config=transport.token_config,
            auth_disabled=transport.auth_disabled,
            default_kingdee_username=service.default_username,
            records=records,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _fingerprint_for_path(path: str) -> tuple[int, int, int, int] | None:
        try:
            stat_result = Path(path).stat()
        except FileNotFoundError:
            return None
        return (stat_result.st_mtime_ns, stat_result.st_ctime_ns, stat_result.st_size, stat_result.st_ino)

    def records_for_request(self) -> dict[str, Any]:
        if self.auth_disabled or not self.token_config:
            return self.records
        fingerprint = self._fingerprint_for_path(self.token_config)
        if fingerprint == self.fingerprint:
            return self.records
        with self._lock:
            fingerprint = self._fingerprint_for_path(self.token_config)
            if fingerprint == self.fingerprint:
                return self.records
            try:
                records = load_token_records(self.token_config)
            except Exception as exc:
                raise AuthError(f"token config reload failed: {exc}") from exc
            self.records = records
            self.fingerprint = fingerprint
            return self.records

    def summary(self) -> dict[str, Any]:
        records = self.records
        try:
            records = self.records_for_request()
        except AuthError:
            records = {}
        return {
            "auth_disabled": self.auth_disabled,
            "token_configured": bool(self.token_config),
            "active_tokens": len([record for record in records.values() if getattr(record, "enabled", False)]),
        }


class KingdeeLiteApplication:
    def __init__(self, service_config: ServiceConfig | None = None, transport_config: TransportConfig | None = None, client: KingdeeWebAPIClient | None = None) -> None:
        self.service_config = service_config or load_service_config()
        self.transport_config = transport_config or load_transport_config()
        self.auth = AuthConfig.load(self.transport_config, self.service_config)
        max_kingdee = int(os.getenv("MCP_MAX_CONCURRENT_KINGDEE_REQUESTS", "4") or "4")
        self.client = client or KingdeeWebAPIClient(self.service_config, max_concurrent_requests=max_kingdee)
        self.tools = build_core_read_tools(self.client)
        self._runner = AsyncLoopRunner()
        self._tool_semaphore = threading.BoundedSemaphore(max(1, int(os.getenv("MCP_MAX_CONCURRENT_TOOLS", "8") or "8")))

    def close(self) -> None:
        self._runner.close()

    def context_from_headers(self, headers: dict[str, str] | None = None) -> OperatorContext:
        headers = headers or {}
        if self.auth.auth_disabled:
            return local_operator_context(self.auth.default_kingdee_username)
        if not self.auth.token_config:
            raise AuthError("MCP_TOKEN_CONFIG is required unless MCP_AUTH_DISABLED=true")
        authorization = headers.get("Authorization") or headers.get("authorization") or ""
        context = authenticate_authorization_header(self.auth.records_for_request(), authorization)
        if context is None:
            raise AuthError("missing or invalid Bearer token")
        return context

    def local_context(self) -> OperatorContext:
        return local_operator_context(self.auth.default_kingdee_username)

    def initialize_result(self) -> dict[str, Any]:
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}

    def list_tools(self, context: OperatorContext) -> list[dict[str, Any]]:
        return [tool.as_mcp_tool() for tool in self.tools.values() if tool_allowed(tool.name, context.allowed_tools)]

    def dispatch(self, request: dict[str, Any], context: OperatorContext) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return jsonrpc_result(request_id, self.initialize_result())
        if method == "ping":
            return jsonrpc_result(request_id, {})
        if method == "tools/list":
            return jsonrpc_result(request_id, {"tools": self.list_tools(context)})
        if method == "resources/list":
            return jsonrpc_result(request_id, {"resources": []})
        if method == "prompts/list":
            return jsonrpc_result(request_id, {"prompts": []})
        if method == "tools/call":
            name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") or {}
            return jsonrpc_result(request_id, self.call_tool(name, arguments, context))
        if request_id is None:
            return None
        return jsonrpc_error(request_id, -32601, f"Method not found: {method}")

    def call_tool(self, name: str, arguments: dict[str, Any], context: OperatorContext) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return tool_result({"ok": False, "error": {"type": "unknown_tool", "message": f"Unknown tool: {name}"}}, is_error=True)
        if not tool_allowed(name, context.allowed_tools):
            return tool_result({"ok": False, "error": {"type": "disallowed_tool", "message": f"Tool is not allowed for this token: {name}"}}, is_error=True)
        try:
            coerced = coerce_arguments(tool.input_schema, arguments)
        except Exception as exc:
            return tool_result({"ok": False, "error": {"type": "invalid_arguments", "message": str(exc)}}, is_error=True)
        acquired = self._tool_semaphore.acquire(timeout=float(os.getenv("MCP_TOOL_QUEUE_TIMEOUT_SECONDS", "3") or "3"))
        if not acquired:
            return tool_result({"ok": False, "error": {"type": "server_busy", "message": "Server is busy; retry later"}}, is_error=True)
        try:
            payload = self._runner.run(tool.handler(coerced, context), timeout=float(os.getenv("MCP_TOOL_CALL_TIMEOUT_SECONDS", "120") or "120"))
            return tool_result(payload)
        except Exception as exc:
            return tool_result({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)[:500]}}, is_error=True)
        finally:
            self._tool_semaphore.release()


def tool_allowed(name: str, allowed_tools: frozenset[str]) -> bool:
    if not allowed_tools:
        return False
    if name in allowed_tools:
        return True
    stable_read_tools = ALL_READ_TOOL_NAMES - EXPERIMENTAL_READ_TOOL_NAMES
    if allowed_tools.intersection({"*", "all", "high"}):
        return name in ALL_LIGHTWEIGHT_TOOL_NAMES - EXPERIMENTAL_READ_TOOL_NAMES
    if allowed_tools.intersection({"read", "core"}):
        return name in CORE_READ_TOOL_NAMES
    if allowed_tools.intersection({"full-read", "read-all"}):
        return name in ALL_READ_TOOL_NAMES
    if "write" in allowed_tools:
        return name in stable_read_tools or name in MIGRATED_WRITE_TOOL_NAMES
    if "ops" in allowed_tools:
        return name in MIGRATED_OPS_TOOL_NAMES
    return False


def coerce_arguments(schema: dict[str, Any], arguments: dict[str, Any] | None) -> dict[str, Any]:
    arguments = dict(arguments or {})
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    unknown = sorted(set(arguments).difference(properties))
    if unknown and schema.get("additionalProperties") is False:
        raise ValueError("unknown arguments: " + ", ".join(unknown))
    result: dict[str, Any] = {}
    for name, prop in properties.items():
        if name in arguments:
            value = arguments[name]
        elif "default" in prop:
            value = prop["default"]
        elif name in required:
            raise ValueError(f"missing required argument: {name}")
        else:
            continue
        result[name] = coerce_value(name, value, prop)
    return result


def coerce_value(name: str, value: Any, prop: dict[str, Any]) -> Any:
    expected = prop.get("type", "string")
    if expected == "integer":
        try:
            ivalue = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
        if "minimum" in prop and ivalue < int(prop["minimum"]):
            raise ValueError(f"{name} must be >= {prop['minimum']}")
        if "maximum" in prop and ivalue > int(prop["maximum"]):
            raise ValueError(f"{name} must be <= {prop['maximum']}")
        return ivalue
    if expected == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
    if expected == "array":
        return value if isinstance(value, list) else [value]
    if expected == "object":
        if isinstance(value, dict):
            return value
        raise ValueError(f"{name} must be an object")
    svalue = str(value or "").strip()
    enum = prop.get("enum")
    if enum and svalue not in enum:
        raise ValueError(f"{name} must be one of: {', '.join(enum)}")
    return svalue


def tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}], "structuredContent": payload, "isError": is_error}


def jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(request_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": payload}


def process_http_request(app: KingdeeLiteApplication, *, method: str, path: str, headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, dict[str, Any]]:
    headers = {str(k): str(v) for k, v in (headers or {}).items()}
    if method == "GET" and path == "/healthz":
        return HTTPStatus.OK, {"ok": True, "server": SERVER_NAME, "version": SERVER_VERSION, "auth": app.auth.summary()}
    if path != app.transport_config.path:
        return HTTPStatus.NOT_FOUND, {"error": "not_found"}
    if method == "OPTIONS":
        return HTTPStatus.NO_CONTENT, {}
    try:
        context = app.context_from_headers(headers)
    except AuthError as exc:
        return HTTPStatus.UNAUTHORIZED, {"error": "missing_or_invalid_bearer", "message": str(exc)}
    if method == "GET":
        return HTTPStatus.OK, {"ok": True, **app.initialize_result(), "auth": {"operator": context.operator, "kingdee_username": context.kingdee_username}}
    if method != "POST":
        return HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"}
    try:
        request = json.loads((body or b"").decode("utf-8"))
    except json.JSONDecodeError:
        return HTTPStatus.BAD_REQUEST, {"error": "invalid_json"}
    response = app.dispatch(request, context)
    if response is None:
        return HTTPStatus.ACCEPTED, {"ok": True}
    return HTTPStatus.OK, response


def _build_http_handler(app: KingdeeLiteApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "KingdeeMCPLite/1.0"
        cors_allow_headers = "Authorization, Content-Type, Accept, CF-Access-Client-Id, CF-Access-Client-Secret, Mcp-Session-Id, mcp-session-id"
        cors_allow_methods = "GET, POST, OPTIONS"

        def _cors_origin(self) -> str | None:
            origin = self.headers.get("Origin")
            if not origin:
                return None
            allowed = app.transport_config.cors_allow_origins
            if not allowed:
                return None
            if "*" in allowed:
                return "*"
            return origin if origin in allowed else None

        def _send_cors_headers(self) -> None:
            allow_origin = self._cors_origin()
            if not allow_origin:
                return
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            if allow_origin != "*":
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", self.cors_allow_headers)
            self.send_header("Access-Control-Allow-Methods", self.cors_allow_methods)
            self.send_header("Access-Control-Max-Age", "300")

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            if status != HTTPStatus.NO_CONTENT:
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            status, payload = process_http_request(app, method="GET", path=self.path, headers={key: value for key, value in self.headers.items()})
            self._send_json(status, payload)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            status, payload = process_http_request(app, method="POST", path=self.path, headers={key: value for key, value in self.headers.items()}, body=self.rfile.read(length))
            self._send_json(status, payload)

        def do_OPTIONS(self) -> None:  # noqa: N802
            status, payload = process_http_request(app, method="OPTIONS", path=self.path, headers={key: value for key, value in self.headers.items()})
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return Handler


def create_http_server(host: str, port: int, app: KingdeeLiteApplication | None = None) -> ThreadingHTTPServer:
    application = app or KingdeeLiteApplication()
    return KingdeeThreadingHTTPServer((host, port), _build_http_handler(application))


def run_http_server(host: str, port: int, app: KingdeeLiteApplication | None = None) -> int:
    application = app or KingdeeLiteApplication()
    server = KingdeeThreadingHTTPServer((host, port), _build_http_handler(application))
    print(json.dumps({"server": SERVER_NAME, "mode": "http", "host": host, "port": port, "path": application.transport_config.path, "auth": application.auth.summary()}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.close()
    return 0


def _read_stdio_message(stream: Any) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", "0") or "0")
    if content_length <= 0:
        return None
    body = stream.read(content_length)
    return json.loads(body.decode("utf-8")) if body else None


def _write_stdio_message(stream: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def run_stdio_server(app: KingdeeLiteApplication | None = None) -> int:
    application = app or KingdeeLiteApplication()
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    try:
        context = application.local_context()
        while True:
            message = _read_stdio_message(stdin)
            if message is None:
                return 0
            response = application.dispatch(message, context)
            if response is not None:
                _write_stdio_message(stdout, response)
    finally:
        application.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kingdee MCP lightweight gateway")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--check", action="store_true", help="check local Kingdee login with KINGDEE_USERNAME")
    return parser


def run_check() -> int:
    app = KingdeeLiteApplication()
    try:
        context = app.local_context()
        app._runner.run(app.client.ensure_session(context), timeout=35)
        print(json.dumps({"ok": True, "server": SERVER_NAME, "kingdee_username": context.kingdee_username}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {str(exc)}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        app.close()


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check:
        return run_check()
    transport = load_transport_config()
    if transport.transport == "stdio":
        return run_stdio_server()
    if transport.transport in {"streamable-http", "sse"}:
        return run_http_server(args.host or transport.host, args.port or transport.port)
    raise SystemExit(f"unsupported MCP_TRANSPORT: {transport.transport}")
