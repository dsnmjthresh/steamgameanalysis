"""SteamAnalysis FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api.routes import (
    aliases,
    chat,
    compare,
    exports,
    games,
    knowledge,
    memory,
    monitors,
    reports,
    reviews,
    settings,
    snapshots,
    tasks,
    web_sentiment,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import render_metrics
from app.core.middleware import (
    AuthMiddleware,
    RequestIdMiddleware,
    RequestSizeLimitMiddleware,
    RequestTimingMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limiter import RateLimitMiddleware
from app.db.session import engine, init_db
from app.schemas.status import ComponentStatus, RuntimeStatus

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("steamanalysis starting up")

    # Validate configuration
    from app.core.config import validate_config_on_startup

    validate_config_on_startup()

    # Initialise database (Alembic migration or create_all)
    init_db()

    # Start background scheduler for monitor tasks
    scheduler = _start_scheduler()

    # Start background task worker
    _start_task_worker()

    yield

    # Shutdown
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
            logger.info("scheduler shut down")
        except Exception:
            pass
    _stop_task_worker()
    logger.info("steamanalysis shut down")


def _start_scheduler():
    """Start the APScheduler for background monitoring tasks (best-effort).

    Controlled by ``STEAMANALYSIS_ENABLE_SCHEDULER`` — set to ``false``,
    ``0``, or ``no`` to disable (useful when running a dedicated scheduler
    service or in development).
    """
    settings = get_settings()
    if not settings.enable_scheduler:
        logger.info("scheduler disabled (STEAMANALYSIS_ENABLE_SCHEDULER=false)")
        return None

    try:
        from app.services.scheduler_service import start_scheduler

        return start_scheduler()
    except Exception as exc:
        logger.warning("scheduler not started: %s", exc)
        return None


def _start_task_worker():
    """Start the background task queue worker (when enabled).

    Controlled by ``STEAMANALYSIS_ENABLE_TASK_WORKER`` — set to ``false``,
    ``0``, or ``no`` to disable (useful when running a dedicated task worker
    service or in testing).
    """
    settings = get_settings()
    if not settings.enable_task_worker:
        logger.info("task worker disabled (STEAMANALYSIS_ENABLE_TASK_WORKER=false)")
        return

    from app.db.session import SessionLocal

    try:
        from app.services.task_queue import start_worker

        start_worker(SessionLocal)
        logger.info("background task worker started")
    except Exception as exc:
        logger.warning("background task worker not started: %s", exc)


def _stop_task_worker():
    """Stop the background task queue worker."""
    try:
        from app.services.task_queue import stop_worker

        stop_worker()
        logger.info("background task worker stopped")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

settings_obj = get_settings()

app = FastAPI(
    title="SteamAnalysis API",
    version="0.2.0",
    description="Public Steam data snapshots and traceable agent analysis.",
    lifespan=lifespan,
)

# ---- Middleware stack ----
#
# Starlette executes the last-added middleware first. Register from inner to
# outer so RequestId wraps the full chain and auth runs before rate limiting.

# Reject oversized request bodies early
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=5 * 1024 * 1024)

# Rate limiting — inside Auth so auth failures don't consume rate-limit budget.
# Disabled when STEAMANALYSIS_RATE_LIMIT_ENABLED=false (the test suite shares one
# in-memory app instance, whose per-IP window would otherwise trip 429 mid-run).
if settings_obj.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=settings_obj.rate_limit_requests_per_minute,
        window_s=settings_obj.rate_limit_window_seconds,
        busy_routes={"/api/chat": settings_obj.rate_limit_chat_per_minute},
    )

# Authentication — outside RateLimit so private routes fail with 401 first
app.add_middleware(AuthMiddleware)

# CORS preflight should be handled before auth/rate-limit when applicable
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings_obj.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers on every response produced downstream
app.add_middleware(SecurityHeadersMiddleware)

# Request timing (logged + exposed in response header)
app.add_middleware(RequestTimingMiddleware)

# Request ID — outermost so all downstream code can access it
app.add_middleware(RequestIdMiddleware)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["health"])
async def health() -> dict:
    """Health check — includes DB and vector-index availability."""
    db_ok = False
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    vec_ok = False
    try:
        from sqlmodel import Session

        from app.services.knowledge_service import _sqlite_vec_available
        with Session(engine) as session:
            vec_ok = _sqlite_vec_available(session)
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "steamanalysis",
        "version": "0.2.0",
        "database": "ok" if db_ok else "unreachable",
        "vector_index": "available" if vec_ok else "unavailable",
    }


@app.get("/api/metrics", tags=["observability"])
async def metrics() -> PlainTextResponse:
    """Prometheus-compatible metrics endpoint."""
    return PlainTextResponse(content=render_metrics(), media_type="text/plain; charset=utf-8")


@app.get("/api/metrics/dashboard", tags=["observability"])
async def metrics_dashboard():
    """Simple HTML dashboard for current metrics."""
    from fastapi.responses import HTMLResponse

    from app.core.metrics import render_metrics_html

    return HTMLResponse(content=render_metrics_html())


@app.get("/api/status", response_model=RuntimeStatus, tags=["observability"])
async def runtime_status() -> RuntimeStatus:
    """Detailed local runtime/dependency status.

    This endpoint intentionally avoids outbound network checks. It reports
    configuration and local capability state so the frontend can distinguish
    usable, degraded, and unavailable modes without making the health check
    slow or costly.
    """
    import os

    settings = get_settings()

    db_status = ComponentStatus(status="unavailable", detail="database connection failed")
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = ComponentStatus(status="ok", detail=settings.database_url)
    except Exception as exc:
        db_status = ComponentStatus(status="unavailable", detail=str(exc))

    vector_status = ComponentStatus(status="degraded", detail="sqlite-vec unavailable; using Python fallback")
    try:
        from sqlmodel import Session

        from app.services.knowledge_service import _sqlite_vec_available

        with Session(engine) as session:
            if _sqlite_vec_available(session):
                vector_status = ComponentStatus(status="ok", detail="sqlite-vec available")
    except Exception as exc:
        vector_status = ComponentStatus(status="degraded", detail=str(exc))

    try:
        from app.llm import get_provider_info

        info = get_provider_info()
        llm_status = ComponentStatus(
            status="ok" if info.available else "degraded",
            detail=(
                f"{info.provider}:{info.model}"
                if info.available
                else f"{info.provider} unavailable: {info.reason}"
            ),
        )
    except Exception as exc:
        llm_status = ComponentStatus(status="degraded", detail=str(exc))

    emb_provider = settings.embedding_provider
    if emb_provider == "openai" and os.getenv("OPENAI_API_KEY"):
        embedding_status = ComponentStatus(status="ok", detail=f"openai:{settings.embedding_model}")
    elif emb_provider == "openai":
        embedding_status = ComponentStatus(status="degraded", detail="OPENAI_API_KEY missing; falls back to hash")
    elif emb_provider == "deepseek":
        embedding_status = ComponentStatus(status="degraded", detail="DeepSeek embeddings unavailable; falls back to hash")
    else:
        embedding_status = ComponentStatus(status="degraded", detail=f"{emb_provider} provider; no semantic embeddings")

    steam_status = ComponentStatus(
        status="ok" if os.getenv("STEAM_API_KEY") else "degraded",
        detail=(
            "STEAM_API_KEY configured"
            if os.getenv("STEAM_API_KEY")
            else "STEAM_API_KEY missing; Store public endpoints may still work"
        ),
    )
    firecrawl_status = ComponentStatus(
        status="ok" if os.getenv("FIRECRAWL_API_KEY") else "unavailable",
        detail="FIRECRAWL_API_KEY configured" if os.getenv("FIRECRAWL_API_KEY") else "FIRECRAWL_API_KEY missing",
    )
    scheduler_status = ComponentStatus(
        status="ok" if settings.enable_scheduler else "unavailable",
        detail="enabled in this process" if settings.enable_scheduler else "disabled in this process",
    )
    task_worker_status = ComponentStatus(
        status="ok" if settings.enable_task_worker else "unavailable",
        detail=(
            "embedded worker enabled"
            if settings.enable_task_worker
            else "embedded worker disabled; use standalone task_worker"
        ),
    )

    return RuntimeStatus(
        service="steamanalysis",
        version="0.2.0",
        environment=settings.env,
        database=db_status,
        vector_index=vector_status,
        llm=llm_status,
        embedding=embedding_status,
        steam_api=steam_status,
        firecrawl=firecrawl_status,
        scheduler=scheduler_status,
        task_worker=task_worker_status,
    )


# ---- API routers ----

app.include_router(games.router, prefix="/api")
app.include_router(aliases.router, prefix="/api")
app.include_router(snapshots.router, prefix="/api")
app.include_router(compare.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(monitors.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(web_sentiment.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
