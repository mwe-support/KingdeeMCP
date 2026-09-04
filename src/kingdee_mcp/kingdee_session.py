from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from .config import ServiceConfig


@dataclass(frozen=True)
class KingdeeSessionKey:
    server_url: str
    acct_id: str
    app_id: str
    kingdee_username: str


@dataclass
class KingdeeSessionEntry:
    session_id: str
    cookie_header: str
    created_at: float
    last_used_at: float
    user_id: int = 0


class KingdeeSessionManager:
    def __init__(self, service_config: ServiceConfig, login_url: Callable[[], str]):
        self._service_config = service_config
        self._login_url = login_url
        self._sessions: dict[KingdeeSessionKey, KingdeeSessionEntry] = {}
        self._locks: dict[KingdeeSessionKey, asyncio.Lock] = {}

    def _key(self, kingdee_username: str) -> KingdeeSessionKey:
        return KingdeeSessionKey(
            server_url=self._service_config.server_url,
            acct_id=self._service_config.acct_id,
            app_id=self._service_config.app_id,
            kingdee_username=kingdee_username,
        )

    def _lock_for(self, key: KingdeeSessionKey) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _is_fresh(self, entry: KingdeeSessionEntry) -> bool:
        ttl = self._service_config.session_ttl_seconds
        if ttl <= 0:
            return True
        return time.time() - entry.created_at < ttl

    async def _get_entry(self, key: KingdeeSessionKey) -> KingdeeSessionEntry:
        entry = self._sessions.get(key)
        if entry and self._is_fresh(entry):
            entry.last_used_at = time.time()
            return entry

        async with self._lock_for(key):
            entry = self._sessions.get(key)
            if entry and self._is_fresh(entry):
                entry.last_used_at = time.time()
                return entry
            self._sessions.pop(key, None)
            return await self._login_locked(key)

    async def get_session(self, kingdee_username: str) -> str:
        return (await self._get_entry(self._key(kingdee_username))).session_id

    async def get_cookie_header(self, kingdee_username: str) -> str:
        return (await self._get_entry(self._key(kingdee_username))).cookie_header

    async def get_user_id(self, kingdee_username: str) -> int:
        user_id = (await self._get_entry(self._key(kingdee_username))).user_id
        if user_id <= 0:
            raise PermissionError("Login response did not include an authenticated Kingdee UserId")
        return user_id

    async def refresh_session(self, kingdee_username: str) -> str:
        key = self._key(kingdee_username)
        async with self._lock_for(key):
            self._sessions.pop(key, None)
            return (await self._login_locked(key)).session_id

    async def refresh_cookie_header(self, kingdee_username: str) -> str:
        key = self._key(kingdee_username)
        async with self._lock_for(key):
            self._sessions.pop(key, None)
            return (await self._login_locked(key)).cookie_header

    def invalidate_session(self, kingdee_username: str) -> None:
        self._sessions.pop(self._key(kingdee_username), None)

    @staticmethod
    def _cookie_header_from_response(resp: httpx.Response, session_id: str) -> str:
        parts: list[str] = []
        seen: set[str] = set()
        cookies = getattr(resp, "cookies", None)
        jar = getattr(cookies, "jar", None)
        for cookie in jar or ():
            name = str(getattr(cookie, "name", "") or "").strip()
            value = str(getattr(cookie, "value", "") or "")
            if not name:
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            parts.append(f"{name}={value}")
        if "kdservice-sessionid" not in seen:
            parts.insert(0, f"kdservice-sessionid={session_id}")
        return "; ".join(parts)

    async def _login_locked(self, key: KingdeeSessionKey) -> KingdeeSessionEntry:
        cfg = self._service_config
        payload = {
            "parameters": [
                cfg.acct_id,
                key.kingdee_username,
                cfg.app_id,
                cfg.app_secret,
                cfg.lcid,
            ]
        }
        async with httpx.AsyncClient(
            timeout=30,
            proxy=None,
            transport=httpx.AsyncHTTPTransport(http1=True),
        ) as client:
            resp = await client.post(
                self._login_url(),
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("LoginResultType") != 1:
                raise RuntimeError(
                    f"Kingdee login failed for {key.kingdee_username}: "
                    f"{data.get('Message', 'unknown error')}"
                )
            session_id = data["KDSVCSessionId"]
            cookie_header = self._cookie_header_from_response(resp, session_id)
            now = time.time()
            entry = KingdeeSessionEntry(
                session_id=session_id,
                cookie_header=cookie_header,
                created_at=now,
                last_used_at=now,
                user_id=int((data.get("Context") or {}).get("UserId") or 0),
            )
            self._sessions[key] = entry
            return entry
