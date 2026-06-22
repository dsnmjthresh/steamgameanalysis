from collections.abc import Generator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from app.core.config import get_settings


def _connect_args(database_url: str) -> dict[str, bool]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


settings = get_settings()
engine: Engine = create_engine(
    settings.database_url,
    echo=settings.env == "development-sql",
    connect_args=_connect_args(settings.database_url),
)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _load_sqlite_vec(dbapi_connection: Any, _: Any) -> None:
        try:
            import sqlite_vec

            dbapi_connection.enable_load_extension(True)
            sqlite_vec.load(dbapi_connection)
        except Exception:
            return
        finally:
            try:
                dbapi_connection.enable_load_extension(False)
            except Exception:
                pass


def _run_alembic_upgrade() -> None:
    """Run pending Alembic migrations. No create_all fallback — migration is required."""
    import os

    from alembic.config import Config as AlembicConfig

    from alembic import command

    # Resolve the alembic.ini path relative to the backend package
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    alembic_ini = os.path.join(backend_dir, "alembic.ini")

    if not os.path.isfile(alembic_ini):
        raise RuntimeError(
            f"alembic.ini not found at {alembic_ini} — database migrations cannot run."
        )

    alembic_cfg = AlembicConfig(alembic_ini)
    # Override the script_location so it resolves relative to backend_dir
    alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))

    # Run migrations — fail fast if something is wrong. No create_all fallback.
    command.upgrade(alembic_cfg, "head")


def init_db() -> None:
    """Initialise database: run migrations, then create FTS/vector virtual tables."""
    _run_alembic_upgrade()
    # Init FTS5 / vec0 virtual tables and seed data (these live outside Alembic)
    with Session(engine) as session:
        from app.services.game_alias_service import seed_default_aliases
        from app.services.knowledge_service import init_knowledge_indexes
        from app.services.memory_service import init_memory_indexes

        init_knowledge_indexes(engine)
        init_memory_indexes(engine)
        seed_default_aliases(session)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def SessionLocal() -> Session:
    """Create a new SQLModel Session (suitable for background workers)."""
    return Session(engine)
