from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


MAX_ACCESS_LOG_RETENTION_DAYS = 30


@dataclass(frozen=True)
class AccessLogConfig:
    path: str
    retention_days: int = MAX_ACCESS_LOG_RETENTION_DAYS

    @property
    def enabled(self) -> bool:
        return bool(self.path)


def load_access_log_config() -> AccessLogConfig:
    path = os.getenv("MCP_ACCESS_LOG_PATH", "").strip()
    raw_retention = os.getenv(
        "MCP_ACCESS_LOG_RETENTION_DAYS",
        str(MAX_ACCESS_LOG_RETENTION_DAYS),
    ).strip()
    try:
        retention_days = int(raw_retention)
    except ValueError as exc:
        raise ValueError("MCP_ACCESS_LOG_RETENTION_DAYS must be an integer") from exc
    if not 1 <= retention_days <= MAX_ACCESS_LOG_RETENTION_DAYS:
        raise ValueError(
            f"MCP_ACCESS_LOG_RETENTION_DAYS must be between 1 and {MAX_ACCESS_LOG_RETENTION_DAYS}"
        )
    return AccessLogConfig(path=path, retention_days=retention_days)


class RetentionTimedRotatingFileHandler(TimedRotatingFileHandler):
    def __init__(self, filename: str, retention_days: int) -> None:
        self.retention_seconds = retention_days * 86400
        super().__init__(
            filename,
            when="midnight",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
            delay=True,
            utc=True,
            errors="backslashreplace",
        )
        self.prune_expired()

    def doRollover(self) -> None:  # noqa: N802
        super().doRollover()
        self.prune_expired()

    def prune_expired(self) -> None:
        cutoff = time.time() - self.retention_seconds
        base_path = Path(self.baseFilename)
        for candidate in base_path.parent.glob(f"{base_path.name}.*"):
            try:
                if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except FileNotFoundError:
                continue


class JsonAccessLogger:
    def __init__(self, config: AccessLogConfig) -> None:
        self.config = config
        self._logger: logging.Logger | None = None
        self._handler: RetentionTimedRotatingFileHandler | None = None
        if not config.enabled:
            return

        log_path = Path(config.path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RetentionTimedRotatingFileHandler(
            str(log_path),
            retention_days=config.retention_days,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.Logger(f"kingdee_mcp.access.{id(self)}", level=logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        self._logger = logger
        self._handler = handler

    def write(self, event: dict[str, Any]) -> None:
        if self._logger is None:
            return
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "event": "mcp_access",
            **event,
        }
        self._logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def close(self) -> None:
        if self._logger is None or self._handler is None:
            return
        self._logger.removeHandler(self._handler)
        self._handler.close()
        self._handler = None
        self._logger = None
