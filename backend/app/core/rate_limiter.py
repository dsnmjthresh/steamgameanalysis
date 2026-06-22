"""IP-based sliding-window rate limiter middleware for FastAPI.

Each IP address gets a configurable number of requests per time window.
Busy routes (e.g. streaming chat) can have a lower per-IP limit.
"""

from __future__ import annotations

import time
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed by client IP.

    Parameters
    ----------
    max_requests:
        Default requests per window for most API routes.
    window_s:
        Duration of the sliding window in seconds.
    busy_routes:
        Mapping of path prefix → per-window limit.  Useful for expensive
        routes like ``/api/chat/stream``.
    """

    def __init__(
        self,
        app,
        max_requests: int = 30,
        window_s: int = 60,
        busy_routes: dict[str, int] | None = None,
    ) -> None:
        super().__init__(app)
        self._max = max_requests
        self._window = window_s
        self._busy: dict[str, int] = busy_routes or {}
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_ip(request: Request) -> str:
        """Extract the client IP, respecting ``X-Forwarded-For``."""
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"

    def _limit_for_path(self, path: str) -> int:
        for prefix, limit in self._busy.items():
            if path.startswith(prefix):
                return limit
        return self._max

    def _check_and_increment(self, ip: str, limit: int, now: float) -> tuple[bool, int]:
        """Return ``(allowed, remaining)`` after atomically updating the window."""
        with self._lock:
            window_start, count = self._windows.get(ip, (now, 0))
            if now - window_start > self._window:
                # Window expired — reset
                window_start, count = now, 0
            count += 1
            self._windows[ip] = (window_start, count)

        remaining = max(0, limit - count)
        return count <= limit, remaining

    # ------------------------------------------------------------------
    # Middleware dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Only rate-limit API routes, and never health/metrics
        if not path.startswith("/api/") or path in ("/api/health", "/api/metrics"):
            return await call_next(request)  # type: ignore[no-any-return]

        ip = self._get_ip(request)
        limit = self._limit_for_path(path)
        now = time.monotonic()
        allowed, remaining = self._check_and_increment(ip, limit, now)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too Many Requests",
                    "remaining": 0,
                    "limit": limit,
                    "window_seconds": self._window,
                },
                headers={"Retry-After": str(self._window)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Limit"] = str(limit)
        return response  # type: ignore[no-any-return]