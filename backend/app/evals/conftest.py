"""Fixtures for eval tests."""

from collections.abc import Generator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture(name="session_with_knowledge")
def session_with_knowledge_fixture() -> Generator[Session, None, None]:
    """Session with FTS5 + vec0 knowledge indexes initialised."""
    import app.db.models  # noqa: F401 — register table metadata

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

    with Session(engine) as session:
        yield session
