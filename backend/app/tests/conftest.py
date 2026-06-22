"""Test fixtures and infrastructure for SteamAnalysis backend tests."""

from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session


@pytest.fixture(name="engine")
def engine_fixture():
    """In-memory SQLite engine for isolated tests."""
    # Ensure all models are registered in SQLModel.metadata before create_all
    import app.db.models  # noqa: F401 — registers table metadata

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine) -> Generator[Session, None, None]:
    """SQLModel Session backed by in-memory SQLite."""
    with Session(engine) as session:
        yield session


@pytest_asyncio.fixture(name="client")
async def client_fixture(engine) -> AsyncIterator[AsyncClient]:
    """httpx AsyncClient wired to the FastAPI app with a test database session."""

    from app.main import app

    def override_get_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(name="engine_with_knowledge")
def engine_with_knowledge_fixture():
    """Engine with FTS5 + vec0 knowledge indexes initialised."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        from app.services.knowledge_service import init_knowledge_indexes

        init_knowledge_indexes(engine)
    except Exception:
        pass
    return engine


@pytest.fixture(name="session_with_knowledge")
def session_with_knowledge_fixture(engine_with_knowledge) -> Generator[Session, None, None]:
    """Session with knowledge indexes ready."""
    with Session(engine_with_knowledge) as session:
        yield session
