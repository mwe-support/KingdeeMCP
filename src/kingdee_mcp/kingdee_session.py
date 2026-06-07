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
    created_at: float
    last_used_at: float


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

    async def get_session(self, kingdee_username: str) -> str:
        key = self._key(kingdee_username)
        entry = self._sessions.get(key)
        if entry:
            entry.last_used_at = time.time()
            return entry.session_id

        async with self._lock_for(key):
            entry = self._sessions.get(key)
            if entry:
                entry.last_used_at = time.time()
                return entry.session_id
            return await self._login_locked(key)

    async def refresh_session(self, kingdee_username: str) -> str:
        key = self._key(kingdee_username)
        async with self._lock_for(key):
            self._sessions.pop(key, None)
            return await self._login_locked(key)

    def invalidate_session(self, kingdee_username: str) -> None:
        self._sessions.pop(self._key(kingdee_username), None)

    async def _login_locked(self, key: KingdeeSessionKey) -> str:
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
            now = time.time()
            self._sessions[key] = KingdeeSessionEntry(
                session_id=session_id,
                created_at=now,
                last_used_at=now,
            )
            return session_id
