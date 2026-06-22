"""Security and observability middleware for FastAPI.

- RequestIdMiddleware : injects X-Request-ID into every response and the logging context
- AuthMiddleware : requires Bearer token when STEAMANALYSIS_AUTH_TOKEN is configured;
  stores a :class:`~app.core.security.Principal` on ``request.state.auth_principal``
- SecurityHeadersMiddleware : adds OWASP-recommended response headers
- RequestSizeLimitMiddleware : rejects oversized request bodies early
"""

from __future__ import annotations

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import generate_request_id, set_request_context
from app.core.security import (
    create_anonymous_principal,
    create_token_principal,
)

_MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign a unique request-id to every HTTP request.

    The ID is stored in a context variable for log correlation and echoed
    back to the client in the ``X-Request-ID`` response header.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        rid = request.headers.get("X-Request-ID", generate_request_id())
        set_request_context(rid, request.url.path)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce authentication based on ``STEAMANALYSIS_AUTH_TOKEN``.

    **When ``auth_token`` is set** (production/secure mode):
        All ``/api/`` routes require a valid ``Bearer`` token except the
        always-public paths (``/api/health``, ``/api/metrics``) and
        OPTIONS preflight requests.

    **When ``auth_token`` is empty** (dev / no-auth mode):
        - **GET / HEAD / OPTIONS** to explicitly public data paths (games,
          aliases, snapshots, health, metrics) are allowed without a token.
        - **GET / HEAD / OPTIONS** to every other ``/api/`` path return
          **401** — unknown API reads are private by default.
        - **POST / PUT / PATCH / DELETE** to any ``/api/`` path return
          **401** — write operations always require a configured token.
    """

    _ALWAYS_PUBLIC: frozenset[str] = frozenset({"/api/health", "/api/status", "/api/metrics"})

    # Public *read* paths available even when no auth_token is configured
    _PUBLIC_READ_PREFIXES: frozenset[str] = frozenset({
        "/api/games",
        "/api/aliases",
        "/api/snapshots",
        "/api/health",
        "/api/status",
        "/api/metrics",
    })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _is_always_public(cls, path: str) -> bool:
        return path in cls._ALWAYS_PUBLIC

    @classmethod
    def _is_public_read_path(cls, path: str) -> bool:
        """Check if *path* starts with one of the public-read prefixes."""
        for prefix in cls._PUBLIC_READ_PREFIXES:
            if path.startswith(prefix):
                return True
        return False

    @classmethod
    def _requires_auth_in_no_token_mode(cls, method: str, path: str) -> bool:
        """Return True when a request must be rejected in no-auth-token mode."""
        # Write operations always require auth
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            return True

        # Read operations are public only for explicit public-read prefixes.
        # This keeps private trace/report-style endpoints from being exposed
        # just because their route is a GET.
        if method in ("GET", "HEAD", "OPTIONS"):
            return not cls._is_public_read_path(path)

        return False

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Always allow health, metrics, OPTIONS — set anonymous principal
        # so downstream code can still inspect the caller identity.
        if self._is_always_public(path) or request.method == "OPTIONS":
            request.state.auth_principal = create_anonymous_principal()
            return await call_next(request)

        # Only gate /api/ paths
        if not path.startswith("/api/"):
            return await call_next(request)

        from app.core.config import get_settings

        settings = get_settings()
        expected = settings.auth_token

        # --- Token IS configured: standard Bearer auth ---
        if expected:
            return await self._verify_bearer(request, call_next, expected)

        # --- Token NOT configured: route-based enforcement ---
        if self._requires_auth_in_no_token_mode(request.method, path):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Authentication required for this resource. "
                        "Set STEAMANALYSIS_AUTH_TOKEN in configuration."
                    )
                },
            )

        # Public read in no-token mode — set anonymous principal
        request.state.auth_principal = create_anonymous_principal()
        return await call_next(request)

    async def _verify_bearer(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
        expected: str,
    ) -> Response:
        """Check the Bearer token and delegate to the next handler on success.

        On success, stores an admin :class:`Principal` on
        ``request.state.auth_principal`` for downstream route guards and
        audit logging.
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401, content={"detail": "Missing Bearer token"}
            )
        token = auth_header[7:]
        if token != expected:
            return JSONResponse(
                status_code=401, content={"detail": "Invalid token"}
            )

        # Valid token — construct the principal and attach to request state
        request.state.auth_principal = create_token_principal(token)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline security headers to every response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        headers.setdefault("X-XSS-Protection", "1; mode=block")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds *max_bytes* with a 413."""

    def __init__(self, app: Any, max_bytes: int = _MAX_BODY_BYTES) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > self._max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    )
            except (ValueError, TypeError):
                pass
        return await call_next(request)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log request method, path, status and latency for every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)

        # Record Prometheus metrics
        from app.core.metrics import record_request

        record_request(request.method, request.url.path, response.status_code, elapsed_ms)

        return response
