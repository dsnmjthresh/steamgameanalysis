"""Tests for auth middleware, Principal/RBAC model, and rate limiting.

Covers:
- Bearer-token auth middleware (existing + new principal integration)
- No-token route-based enforcement (existing)
- Principal / Role / Scope data model
- Principal factory functions
- Principal attachment to request.state
- Rate limiting (existing)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.core.security import (
    Principal,
    Roles,
    Scopes,
    create_anonymous_principal,
    create_token_principal,
    get_principal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_auth_settings():
    """Settings with no auth token configured."""
    from app.core.config import Settings

    return Settings(auth_token="")


def _with_auth_settings():
    """Settings with a token configured."""
    from app.core.config import Settings

    return Settings(auth_token="secret-token")


# ---------------------------------------------------------------------------
# Principal unit tests (pure data class)
# ---------------------------------------------------------------------------


class TestPrincipal:
    """Unit tests for the Principal dataclass and its scope helpers."""

    def test_has_scope_true(self):
        p = Principal(
            subject="u:1", role="admin",
            scopes=frozenset({Scopes.GAMES_READ, Scopes.MEMORY_WRITE}),
            is_authenticated=True,
        )
        assert p.has_scope(Scopes.GAMES_READ) is True
        assert p.has_scope(Scopes.MEMORY_WRITE) is True

    def test_has_scope_false(self):
        p = Principal(
            subject="u:1", role="admin",
            scopes=frozenset({Scopes.GAMES_READ}),
            is_authenticated=True,
        )
        assert p.has_scope(Scopes.GAMES_WRITE) is False

    def test_has_any_scope_matches_one(self):
        p = Principal(
            subject="u:1", role="admin",
            scopes=frozenset({Scopes.GAMES_READ}),
            is_authenticated=True,
        )
        assert p.has_any_scope(Scopes.GAMES_READ, Scopes.GAMES_WRITE) is True

    def test_has_any_scope_matches_none(self):
        p = Principal(
            subject="u:1", role="admin",
            scopes=frozenset({Scopes.GAMES_READ}),
            is_authenticated=True,
        )
        assert p.has_any_scope(Scopes.GAMES_WRITE, Scopes.MEMORY_WRITE) is False

    def test_has_all_scopes_true(self):
        p = Principal(
            subject="u:1", role="admin",
            scopes=frozenset({Scopes.GAMES_READ, Scopes.GAMES_WRITE}),
            is_authenticated=True,
        )
        assert p.has_all_scopes(Scopes.GAMES_READ, Scopes.GAMES_WRITE) is True

    def test_has_all_scopes_false(self):
        p = Principal(
            subject="u:1", role="admin",
            scopes=frozenset({Scopes.GAMES_READ}),
            is_authenticated=True,
        )
        assert p.has_all_scopes(Scopes.GAMES_READ, Scopes.GAMES_WRITE) is False

    def test_anonymous_principal(self):
        p = create_anonymous_principal()
        assert p.subject == "anonymous"
        assert p.role == Roles.PUBLIC
        assert p.is_authenticated is False
        assert Scopes.GAMES_READ in p.scopes
        assert Scopes.SNAPSHOTS_READ in p.scopes
        assert Scopes.HEALTH_READ in p.scopes
        assert Scopes.METRICS_READ in p.scopes
        # Anonymous MUST NOT have write or sensitive scopes
        assert Scopes.GAMES_WRITE not in p.scopes
        assert Scopes.MEMORY_READ not in p.scopes
        assert Scopes.MEMORY_WRITE not in p.scopes
        assert Scopes.SETTINGS_READ not in p.scopes
        assert Scopes.REPORTS_READ not in p.scopes

    def test_token_principal_is_admin(self):
        p = create_token_principal("any-token")
        assert p.subject == "token:default"
        assert p.role == Roles.ADMIN
        assert p.is_authenticated is True
        assert p.metadata.get("auth_method") == "bearer_token"
        # Admin should have all scopes
        assert Scopes.GAMES_READ in p.scopes
        assert Scopes.GAMES_WRITE in p.scopes
        assert Scopes.MEMORY_READ in p.scopes
        assert Scopes.MEMORY_WRITE in p.scopes
        assert Scopes.SETTINGS_READ in p.scopes
        assert Scopes.SETTINGS_WRITE in p.scopes
        assert Scopes.REPORTS_READ in p.scopes
        assert Scopes.REPORTS_WRITE in p.scopes
        # Admin should NOT have the public role
        assert p.role != Roles.PUBLIC

    def test_principal_metadata_default(self):
        p = Principal(subject="s", role="r", scopes=frozenset(), is_authenticated=False)
        assert p.metadata == {}

    def test_get_principal_returns_none_when_not_set(self):
        """get_principal returns None when request.state has no auth_principal."""
        # Simulate a request without AuthMiddleware having run
        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [], "query_string": b"", "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = Request(scope)
        assert get_principal(request) is None

    def test_get_principal_returns_principal_when_set(self):
        """get_principal returns the principal stored by AuthMiddleware."""
        from starlette.requests import Request as StarletteRequest

        scope = {
            "type": "http", "method": "GET", "path": "/api/health",
            "headers": [], "query_string": b"", "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)
        request.state.auth_principal = create_anonymous_principal()
        p = get_principal(request)
        assert p is not None
        assert p.subject == "anonymous"
        assert p.role == Roles.PUBLIC


# ---------------------------------------------------------------------------
# Scope / Role coverage
# ---------------------------------------------------------------------------


class TestScopesAndRoles:
    """Verify scope definitions cover all required resource prefixes."""

    def test_public_scopes_are_read_only(self):
        from app.core.security import ROLE_SCOPES

        public = ROLE_SCOPES[Roles.PUBLIC]
        for s in public:
            assert s.endswith(":read"), f"Public scope {s} must be read-only"

    def test_admin_has_all_scopes(self):
        from app.core.security import ROLE_SCOPES

        admin = ROLE_SCOPES[Roles.ADMIN]
        # Every scope defined as a class attribute of Scopes should be in admin
        all_scope_values = {
            v for k, v in vars(Scopes).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        missing = all_scope_values - admin
        assert not missing, f"Admin missing scopes: {missing}"

    def test_required_write_scopes_exist(self):
        """Verify write scopes exist for resources that need them."""
        required_writes = [
            ("games", Scopes.GAMES_WRITE),
            ("snapshots", Scopes.SNAPSHOTS_WRITE),
            ("memory", Scopes.MEMORY_WRITE),
            ("knowledge", Scopes.KNOWLEDGE_WRITE),
            ("reports", Scopes.REPORTS_WRITE),
            ("settings", Scopes.SETTINGS_WRITE),
            ("monitors", Scopes.MONITORS_WRITE),
            ("compare", Scopes.COMPARE_WRITE),
            ("exports", Scopes.EXPORTS_WRITE),
            ("tasks", Scopes.TASKS_WRITE),
            ("chat", Scopes.CHAT_WRITE),
            ("web_sentiment", Scopes.WEB_SENTIMENT_WRITE),
        ]
        for name, scope in required_writes:
            assert scope.endswith(":write"), f"{name} write scope malformed: {scope}"

    def test_required_read_scopes_exist(self):
        """Verify read scopes exist for resources that need them."""
        required_reads = [
            ("games", Scopes.GAMES_READ),
            ("snapshots", Scopes.SNAPSHOTS_READ),
            ("aliases", Scopes.ALIASES_READ),
            ("reviews", Scopes.REVIEWS_READ),
            ("memory", Scopes.MEMORY_READ),
            ("knowledge", Scopes.KNOWLEDGE_READ),
            ("reports", Scopes.REPORTS_READ),
            ("settings", Scopes.SETTINGS_READ),
            ("monitors", Scopes.MONITORS_READ),
            ("compare", Scopes.COMPARE_READ),
            ("exports", Scopes.EXPORTS_READ),
            ("tasks", Scopes.TASKS_READ),
            ("chat", Scopes.CHAT_READ),
            ("web_sentiment", Scopes.WEB_SENTIMENT_READ),
        ]
        for name, scope in required_reads:
            assert scope.endswith(":read"), f"{name} read scope malformed: {scope}"


# ---------------------------------------------------------------------------
# Principal integration tests via middleware
# ---------------------------------------------------------------------------


class TestPrincipalIntegration:
    """Integration tests verifying principal is set on request.state by middleware.

    Uses direct ``AuthMiddleware.dispatch()`` calls (same pattern as the
    rate-limiter tests) so we can inspect the principal via a controlled
    ``call_next`` callback without depending on route registration order.
    """

    @pytest.mark.anyio
    async def test_always_public_sets_anonymous_principal(self):
        """Dispatch for /api/health (always-public) sets anonymous principal."""
        from unittest.mock import AsyncMock

        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse as StarletteJSONResponse

        from app.core.middleware import AuthMiddleware

        async def call_next(request):
            p = get_principal(request)
            assert p is not None, "Principal must be set for always-public paths"
            return StarletteJSONResponse({
                "subject": p.subject,
                "role": p.role,
                "is_authenticated": p.is_authenticated,
            })

        middleware = AuthMiddleware(app=AsyncMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/health",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)

        with (
            patch("app.core.config.get_settings", return_value=_with_auth_settings()),
        ):
            response = await middleware.dispatch(request, call_next)

        import json

        data = json.loads(response.body)
        assert data["subject"] == "anonymous"
        assert data["role"] == Roles.PUBLIC
        assert data["is_authenticated"] is False

    @pytest.mark.anyio
    async def test_valid_token_sets_admin_principal(self):
        """Dispatch with valid Bearer token sets admin principal."""
        from unittest.mock import AsyncMock

        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse as StarletteJSONResponse

        from app.core.middleware import AuthMiddleware

        async def call_next(request):
            p = get_principal(request)
            assert p is not None, "Principal must be set for valid token"
            return StarletteJSONResponse({
                "subject": p.subject,
                "role": p.role,
                "is_authenticated": p.is_authenticated,
            })

        middleware = AuthMiddleware(app=AsyncMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/games/search",
            "headers": [
                (b"authorization", b"Bearer secret-token"),
            ],
            "query_string": b"query=CS2",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)

        with (
            patch("app.core.config.get_settings", return_value=_with_auth_settings()),
        ):
            response = await middleware.dispatch(request, call_next)

        import json

        data = json.loads(response.body)
        assert data["subject"] == "token:default"
        assert data["role"] == Roles.ADMIN
        assert data["is_authenticated"] is True

    @pytest.mark.anyio
    async def test_no_token_public_read_sets_anonymous_principal(self):
        """Dispatch for public GET (no token) sets anonymous principal."""
        from unittest.mock import AsyncMock

        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse as StarletteJSONResponse

        from app.core.middleware import AuthMiddleware

        async def call_next(request):
            p = get_principal(request)
            assert p is not None, "Principal must be set for public read paths"
            return StarletteJSONResponse({
                "subject": p.subject,
                "role": p.role,
                "is_authenticated": p.is_authenticated,
            })

        middleware = AuthMiddleware(app=AsyncMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/games/search",
            "headers": [],
            "query_string": b"query=CS2",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)

        with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
            response = await middleware.dispatch(request, call_next)

        import json

        data = json.loads(response.body)
        assert data["subject"] == "anonymous"
        assert data["role"] == Roles.PUBLIC
        assert data["is_authenticated"] is False

    @pytest.mark.anyio
    async def test_no_token_sensitive_read_401_and_no_handler_called(self):
        """Dispatch for sensitive GET (no token) returns 401 without calling next."""
        from unittest.mock import AsyncMock

        from starlette.requests import Request as StarletteRequest

        from app.core.middleware import AuthMiddleware

        handler_called = False

        async def call_next(request):
            nonlocal handler_called
            handler_called = True
            from starlette.responses import Response

            return Response(status_code=200)

        middleware = AuthMiddleware(app=AsyncMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/memory",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)

        with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        assert not handler_called, (
            "Route handler must not be called for rejected sensitive reads"
        )

    @pytest.mark.anyio
    async def test_no_token_write_rejected_401(self):
        """Dispatch for POST (no token) returns 401 without calling next."""
        from unittest.mock import AsyncMock

        from starlette.requests import Request as StarletteRequest

        from app.core.middleware import AuthMiddleware

        handler_called = False

        async def call_next(request):
            nonlocal handler_called
            handler_called = True
            from starlette.responses import Response

            return Response(status_code=200)

        middleware = AuthMiddleware(app=AsyncMock())
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/games/730/snapshots",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)

        with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        assert not handler_called, (
            "Route handler must not be called for rejected writes"
        )

    @pytest.mark.anyio
    async def test_wrong_bearer_401_and_no_handler_called(self):
        """Dispatch with wrong Bearer token returns 401 without calling next."""
        from unittest.mock import AsyncMock

        from starlette.requests import Request as StarletteRequest

        from app.core.middleware import AuthMiddleware

        handler_called = False

        async def call_next(request):
            nonlocal handler_called
            handler_called = True
            from starlette.responses import Response

            return Response(status_code=200)

        middleware = AuthMiddleware(app=AsyncMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/games/search",
            "headers": [
                (b"authorization", b"Bearer wrong-token"),
            ],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)

        with (
            patch("app.core.config.get_settings", return_value=_with_auth_settings()),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        assert not handler_called, (
            "Route handler must not be called for rejected wrong tokens"
        )

    @pytest.mark.anyio
    async def test_missing_bearer_401_and_no_handler_called(self):
        """Dispatch with no Bearer header when token is configured returns 401."""
        from unittest.mock import AsyncMock

        from starlette.requests import Request as StarletteRequest

        from app.core.middleware import AuthMiddleware

        handler_called = False

        async def call_next(request):
            nonlocal handler_called
            handler_called = True
            from starlette.responses import Response

            return Response(status_code=200)

        middleware = AuthMiddleware(app=AsyncMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/games/search",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        request = StarletteRequest(scope)

        with (
            patch("app.core.config.get_settings", return_value=_with_auth_settings()),
        ):
            response = await middleware.dispatch(request, call_next)

        assert response.status_code == 401
        assert not handler_called, (
            "Route handler must not be called for missing Bearer"
        )


# ---------------------------------------------------------------------------
# Auth: no auth_token configured (existing tests — preserved)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_token_health_always_ok(client):
    """Health endpoint is always public."""
    with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
        response = await client.get("/api/health")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_no_token_get_public_path_ok(client):
    """GET to a public path succeeds when auth_token is not configured."""
    with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
        response = await client.get("/api/health")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_no_token_get_sensitive_path_401(client):
    """GET to memory (sensitive) returns 401 when auth_token is not configured."""
    with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
        response = await client.get("/api/memory")
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert "STEAMANALYSIS_AUTH_TOKEN" in detail


@pytest.mark.anyio
async def test_no_token_get_reports_401(client):
    """GET to reports (sensitive) returns 401 when auth_token is not configured."""
    with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
        response = await client.get("/api/reports")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_no_token_get_settings_401(client):
    """GET to settings (sensitive) returns 401 when auth_token is not configured."""
    with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
        response = await client.get("/api/settings")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_no_token_get_chat_run_trace_401(client):
    """GET to agent run traces returns 401 when auth_token is not configured."""
    with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
        response = await client.get("/api/chat/runs/test-trace-id")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_no_token_post_write_401(client):
    """POST to any /api/ path returns 401 when auth_token is not configured."""
    with patch("app.core.config.get_settings", return_value=_no_auth_settings()):
        response = await client.post("/api/games/730/snapshots", json={})
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert "STEAMANALYSIS_AUTH_TOKEN" in detail


# ---------------------------------------------------------------------------
# Auth: auth_token IS configured (existing tests — preserved)
# ---------------------------------------------------------------------------


def _mock_steam_client():
    """Create a mock SteamClient that works with ``async with``."""

    mock_steam = AsyncMock()
    mock_steam.search_games = AsyncMock(return_value=[])
    mock_steam.get_current_players = AsyncMock(return_value=({}, "", None))
    mock_steam.get_appdetails = AsyncMock(return_value=({}, "", None))
    mock_steam.get_game_news = AsyncMock(return_value=([], "", None))

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_steam)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_cls


@pytest.mark.anyio
async def test_with_token_missing_bearer_401(client):
    """Missing Bearer header returns 401 when token is configured."""
    # Use /api/games/search (not health — health is always public)
    with (
        patch("app.core.config.get_settings", return_value=_with_auth_settings()),
        patch("app.api.routes.games.SteamClient", _mock_steam_client()),
    ):
        response = await client.get("/api/games/search?query=CS2")
    assert response.status_code == 401
    assert "Missing Bearer" in response.json()["detail"]


@pytest.mark.anyio
async def test_with_token_valid_bearer_ok(client):
    """Valid Bearer token allows access when token is configured."""
    with (
        patch("app.core.config.get_settings", return_value=_with_auth_settings()),
        patch("app.api.routes.games.SteamClient", _mock_steam_client()),
    ):
        response = await client.get(
            "/api/games/search?query=CS2",
            headers={"Authorization": "Bearer secret-token"},
        )
    # Not 401 — token was accepted
    assert response.status_code != 401


@pytest.mark.anyio
async def test_with_token_wrong_bearer_401(client):
    """Wrong Bearer token returns 401 when token is configured."""
    with (
        patch("app.core.config.get_settings", return_value=_with_auth_settings()),
        patch("app.api.routes.games.SteamClient", _mock_steam_client()),
    ):
        response = await client.get(
            "/api/games/search?query=CS2",
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert response.status_code == 401
    assert "Invalid token" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Rate limiting — unit tests on RateLimitMiddleware directly (existing)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rate_limiter_allows_up_to_limit():
    """Within limit, requests pass through; over limit returns 429."""
    from starlette.requests import Request
    from starlette.responses import Response

    from app.core.rate_limiter import RateLimitMiddleware

    limiter = RateLimitMiddleware(
        app=AsyncMock(return_value=Response(status_code=200)),
        max_requests=3,
        window_s=60,
    )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/games/search",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    request = Request(scope)

    async def call_next(req):
        return Response(status_code=200)

    # First 3 should pass through
    for _ in range(3):
        r = await limiter.dispatch(request, call_next)
        assert r.status_code == 200

    # 4th should be rate limited
    r4 = await limiter.dispatch(request, call_next)
    assert r4.status_code == 429
    import json
    data = json.loads(r4.body)
    assert "Too Many Requests" in data["detail"]


@pytest.mark.anyio
async def test_rate_limiter_health_exempt():
    """Health/metrics paths are exempt from rate limiting."""
    from starlette.requests import Request
    from starlette.responses import Response

    from app.core.rate_limiter import RateLimitMiddleware

    limiter = RateLimitMiddleware(
        app=AsyncMock(return_value=Response(status_code=200)),
        max_requests=1,
        window_s=60,
    )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/health",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    request = Request(scope)

    async def call_next(req):
        return Response(status_code=200)

    # Multiple requests should never be rate-limited
    for _ in range(5):
        response = await limiter.dispatch(request, call_next)
        assert response.status_code == 200


@pytest.mark.anyio
async def test_rate_limiter_window_reset():
    """After window expires, requests are allowed again."""
    import asyncio

    from starlette.requests import Request
    from starlette.responses import Response

    from app.core.rate_limiter import RateLimitMiddleware

    limiter = RateLimitMiddleware(
        app=AsyncMock(return_value=Response(status_code=200)),
        max_requests=2,
        window_s=1,  # 1 second window
    )

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/games/search",
        "headers": [],
        "query_string": b"",
        "client": ("10.0.0.1", 54321),
        "server": ("testserver", 80),
    }
    request = Request(scope)

    async def call_next(req):
        return Response(status_code=200)

    # Use up the limit
    assert (await limiter.dispatch(request, call_next)).status_code == 200
    assert (await limiter.dispatch(request, call_next)).status_code == 200
    assert (await limiter.dispatch(request, call_next)).status_code == 429

    # Wait for window to expire
    await asyncio.sleep(1.1)

    # Now should be allowed again
    assert (await limiter.dispatch(request, call_next)).status_code == 200
