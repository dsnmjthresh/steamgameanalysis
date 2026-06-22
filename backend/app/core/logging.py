"""Structured logging with request-id propagation and JSON output support.

Usage::

    from app.core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("snapshot collected", extra={"appid": 730, "latency_ms": 42})
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Any

# Context variable shared across a single request lifecycle
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_request_path_var: ContextVar[str] = ContextVar("request_path", default="-")


def generate_request_id() -> str:
    """Return a short unique request ID (12 hex chars)."""
    return uuid.uuid4().hex[:12]


def set_request_context(request_id: str, path: str = "-") -> None:
    """Store the current request ID and path for the lifetime of this request."""
    _request_id_var.set(request_id)
    _request_path_var.set(path)


def get_request_id() -> str:
    """Return the request ID for the current context or ``"-"``."""
    return _request_id_var.get()


# ---------------------------------------------------------------------------
# JSON formatter (production) / text formatter (development)
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "rid": _request_id_var.get(),
            "path": _request_path_var.get(),
        }
        if record.exc_info and record.exc_info[1]:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra dict passed via logger.info(..., extra={...})
        for key in ("appid", "latency_ms", "tool", "status", "model", "detail"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        return json.dumps(payload, ensure_ascii=False, default=str)


class _TextFormatter(logging.Formatter):
    """Human-readable logs with request-id prefix (development)."""

    def format(self, record: logging.LogRecord) -> str:
        rid = _request_id_var.get()
        prefix = f"[{rid}]" if rid != "-" else ""
        base = super().format(record)
        return f"{prefix} {base}".strip()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    """Set up the root logger based on ``STEAMANALYSIS_LOG_LEVEL`` and ``STEAMANALYSIS_LOG_FORMAT``."""
    level_name = os.getenv("STEAMANALYSIS_LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("STEAMANALYSIS_LOG_FORMAT", "text").lower()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            _TextFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )

    # Capture everything at the root and let handlers filter
    root = logging.getLogger()
    root.setLevel(level)
    # Remove any previously attached handlers to avoid duplicates
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("steamanalysis").info(
        "logging configured (level=%s, format=%s)", level_name, log_format
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for *name* (convenience wrapper)."""
    return logging.getLogger(name)
