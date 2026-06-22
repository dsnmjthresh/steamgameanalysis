"""Secrets, authentication principals, roles, and scope-based authorisation.

Core abstractions
-----------------
- **Scopes** : fine-grained permission strings (``games:read``, ``memory:write``, …)
- **Roles**  : named role labels (``public``, ``admin``, future ``user``, …)
- **Principal** : the authenticated (or anonymous) caller identity carried
  through the request lifecycle.

These are deliberately database-free — they model the *authorisation* layer.
Future user/role tables will *populate* Principals, but the middleware and
route guards only depend on this module, not on any particular storage.

Existing secret-management helpers (``get_secret``, ``key_status``,
``redact_secret``, ``load_local_env``) remain unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from starlette.requests import Request

# ---------------------------------------------------------------------------
# Existing secret helpers — unchanged public API
# ---------------------------------------------------------------------------

SECRET_KEYS = {"DEEPSEEK_API_KEY", "STEAM_API_KEY", "FIRECRAWL_API_KEY"}
_DOTENV_LOADED = False


def load_local_env() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    load_dotenv(override=False)
    _DOTENV_LOADED = True


def get_secret(key: str, environ: Mapping[str, str] | None = None) -> str | None:
    if environ is None:
        load_local_env()
        environ = os.environ
    return environ.get(key)


def key_status(environ: Mapping[str, str] | None = None) -> dict[str, bool]:
    if environ is None:
        load_local_env()
        source = os.environ  # type: ignore[assignment]
    else:
        source = environ  # type: ignore[assignment]
    return {key.lower(): bool(source.get(key)) for key in SECRET_KEYS}


def redact_secret(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


# ---------------------------------------------------------------------------
# Scope constants
# ---------------------------------------------------------------------------


class Scopes:
    """Fine-grained permission scopes.

    Naming convention: ``<resource>:<action>``.  New resources should add
    their scopes here so that route guards and tests stay consistent.
    """

    # -- Public read ---------------------------------------------------------
    GAMES_READ = "games:read"
    SNAPSHOTS_READ = "snapshots:read"
    ALIASES_READ = "aliases:read"
    REVIEWS_READ = "reviews:read"
    HEALTH_READ = "health:read"
    METRICS_READ = "metrics:read"

    # -- Authenticated read --------------------------------------------------
    MEMORY_READ = "memory:read"
    KNOWLEDGE_READ = "knowledge:read"
    REPORTS_READ = "reports:read"
    SETTINGS_READ = "settings:read"
    MONITORS_READ = "monitors:read"
    COMPARE_READ = "compare:read"
    EXPORTS_READ = "exports:read"
    TASKS_READ = "tasks:read"
    CHAT_READ = "chat:read"
    WEB_SENTIMENT_READ = "web_sentiment:read"

    # -- Write ---------------------------------------------------------------
    GAMES_WRITE = "games:write"
    SNAPSHOTS_WRITE = "snapshots:write"
    MEMORY_WRITE = "memory:write"
    KNOWLEDGE_WRITE = "knowledge:write"
    REPORTS_WRITE = "reports:write"
    SETTINGS_WRITE = "settings:write"
    MONITORS_WRITE = "monitors:write"
    COMPARE_WRITE = "compare:write"
    EXPORTS_WRITE = "exports:write"
    TASKS_WRITE = "tasks:write"
    CHAT_WRITE = "chat:write"
    WEB_SENTIMENT_WRITE = "web_sentiment:write"

    # -- Admin / management (future) -----------------------------------------


# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------


class Roles:
    """Named role labels.

    Future: ``Roles.USER``, ``Roles.MODERATOR``, ``Roles.ANALYST``.
    """

    PUBLIC = "public"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Role → granted scopes
# ---------------------------------------------------------------------------

#: Scopes granted to the anonymous / unauthenticated principal.
_PUBLIC_SCOPES: frozenset[str] = frozenset(
    {
        Scopes.GAMES_READ,
        Scopes.SNAPSHOTS_READ,
        Scopes.ALIASES_READ,
        Scopes.REVIEWS_READ,
        Scopes.HEALTH_READ,
        Scopes.METRICS_READ,
    }
)

#: Scopes granted to the admin principal (full access).
_ADMIN_SCOPES: frozenset[str] = frozenset(
    {
        # Read
        Scopes.GAMES_READ,
        Scopes.SNAPSHOTS_READ,
        Scopes.ALIASES_READ,
        Scopes.REVIEWS_READ,
        Scopes.HEALTH_READ,
        Scopes.METRICS_READ,
        Scopes.MEMORY_READ,
        Scopes.KNOWLEDGE_READ,
        Scopes.REPORTS_READ,
        Scopes.SETTINGS_READ,
        Scopes.MONITORS_READ,
        Scopes.COMPARE_READ,
        Scopes.EXPORTS_READ,
        Scopes.TASKS_READ,
        Scopes.CHAT_READ,
        Scopes.WEB_SENTIMENT_READ,
        # Write
        Scopes.GAMES_WRITE,
        Scopes.SNAPSHOTS_WRITE,
        Scopes.MEMORY_WRITE,
        Scopes.KNOWLEDGE_WRITE,
        Scopes.REPORTS_WRITE,
        Scopes.SETTINGS_WRITE,
        Scopes.MONITORS_WRITE,
        Scopes.COMPARE_WRITE,
        Scopes.EXPORTS_WRITE,
        Scopes.TASKS_WRITE,
        Scopes.CHAT_WRITE,
        Scopes.WEB_SENTIMENT_WRITE,
    }
)

ROLE_SCOPES: dict[str, frozenset[str]] = {
    Roles.PUBLIC: _PUBLIC_SCOPES,
    Roles.ADMIN: _ADMIN_SCOPES,
}


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


@dataclass
class Principal:
    """Caller identity carried through the request lifecycle.

    Attributes
    ----------
    subject:
        Stable, human-readable identifier for this principal.
        ``"anonymous"`` for unauthenticated callers;
        ``"token:<sha>"`` for Bearer-token-authenticated callers;
        future: ``"user:<uuid>"`` for database-backed users.
    role:
        Role label from :class:`Roles`.  Used for coarse-grained checks.
    scopes:
        Set of :class:`Scopes` strings this principal is authorised for.
    is_authenticated:
        ``True`` when the caller presented valid credentials.
    metadata:
        Opaque extensibility bag.  Future use: user-id, team-id,
        rate-limit tier, session expiry, etc.
    """

    subject: str
    role: str
    scopes: frozenset[str]
    is_authenticated: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- Scope checks --------------------------------------------------------

    def has_scope(self, scope: str) -> bool:
        """Return ``True`` if this principal holds *scope*."""
        return scope in self.scopes

    def has_any_scope(self, *scopes: str) -> bool:
        """Return ``True`` if this principal holds **any** of *scopes*."""
        return bool(self.scopes.intersection(scopes))

    def has_all_scopes(self, *scopes: str) -> bool:
        """Return ``True`` if this principal holds **all** of *scopes*."""
        return self.scopes.issuperset(scopes)


# ---------------------------------------------------------------------------
# Principal factories
# ---------------------------------------------------------------------------


def create_anonymous_principal() -> Principal:
    """Return the principal for an unauthenticated request.

    The anonymous principal can read public data (games, snapshots, health,
    etc.) but cannot access sensitive endpoints or perform writes.
    """
    return Principal(
        subject="anonymous",
        role=Roles.PUBLIC,
        scopes=ROLE_SCOPES[Roles.PUBLIC],
        is_authenticated=False,
    )


def create_token_principal(token: str) -> Principal:
    """Return the admin principal for a valid Bearer token.

    For now every valid token maps to the ``admin`` role with full scopes.
    When user tables are introduced this factory will look up the actual
    user and its granted roles/scopes.
    """
    return Principal(
        subject="token:default",
        role=Roles.ADMIN,
        scopes=ROLE_SCOPES[Roles.ADMIN],
        is_authenticated=True,
        metadata={"auth_method": "bearer_token"},
    )


# ---------------------------------------------------------------------------
# Request helper
# ---------------------------------------------------------------------------


def get_principal(request: Request) -> Principal | None:
    """Retrieve the :class:`Principal` stored by :class:`AuthMiddleware`.

    Returns ``None`` when the middleware has not run (e.g. before
    ``AuthMiddleware`` is added to the stack) or the request was rejected.
    """
    return getattr(request.state, "auth_principal", None)
