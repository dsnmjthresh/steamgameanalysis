from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import KnowledgeDocument
from app.schemas.knowledge import KnowledgeDocumentCreate, KnowledgeSearchRequest
from app.services.knowledge_service import (
    build_chunks,
    create_document,
    init_knowledge_indexes,
    search_knowledge,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    init_knowledge_indexes(engine)
    return Session(engine)


def test_rag_search_returns_hybrid_ranked_hit() -> None:
    with _session() as session:
        document = create_document(
            session,
            KnowledgeDocumentCreate(
                title="老头环周报",
                source_type="report",
                appid=1245620,
                content=(
                    "# 玩家趋势\n\n"
                    "老头环在周末在线人数上升，玩家讨论集中在 DLC、Boss 难度和折扣。\n\n"
                    "# 价格\n\n"
                    "当前没有明显新低价，但愿望单热度仍然稳定。"
                ),
            ),
        )
        result = search_knowledge(
            session,
            KnowledgeSearchRequest(query="老头环 玩家趋势 DLC", appid=1245620, limit=3),
        )

    assert document.chunk_count >= 1
    assert result.hits
    assert result.hits[0].document_id == document.id
    assert "老头环" in result.hits[0].content
    assert result.debug["vector_backend"] in {"sqlite-vec", "python-cosine"}


def test_python_chunking_prefers_function_boundaries() -> None:
    chunks = build_chunks(
        "def collect_snapshot():\n    return 1\n\nclass Agent:\n    def run(self):\n        return 2\n",
        source_type="python",
        chunk_size_tokens=200,
        chunk_overlap_tokens=20,
    )

    headings = [chunk.heading for chunk in chunks]
    assert "FunctionDef:collect_snapshot" in headings
    assert "ClassDef:Agent" in headings


def test_create_document_rolls_back_on_embedding_failure() -> None:
    """When embedding fails mid-way, no orphan document should be left behind."""
    with _session() as session:
        # Simulate an embedding failure after the first chunk
        with patch(
            "app.services.knowledge_service.embed_text",
            side_effect=RuntimeError("Simulated embedding API failure"),
        ):
            with pytest.raises(RuntimeError, match="Simulated embedding API failure"):
                create_document(
                    session,
                    KnowledgeDocumentCreate(
                        title="Should Roll Back",
                        source_type="note",
                        content="Some content that would be chunked and embedded.",
                    ),
                )

        # The transaction should have been rolled back — no document exists
        count = session.exec(select(KnowledgeDocument)).all()
        assert len(count) == 0, "Orphan document was left behind after embedding failure"


def test_create_document_succeeds_with_hash_fallback() -> None:
    """With the default hash provider, create_document should work end-to-end."""
    with _session() as session:
        document = create_document(
            session,
            KnowledgeDocumentCreate(
                title="Hash-backed Document",
                source_type="note",
                content="This document uses hash embeddings so it always works.",
            ),
        )
        assert document.id is not None
        assert document.id > 0
        assert document.chunk_count >= 1
        # Verify chunks have embedding JSON stored
        from app.db.models import KnowledgeChunk

        chunks = session.exec(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
        ).all()
        assert len(chunks) == document.chunk_count
        for chunk in chunks:
            assert chunk.embedding_json is not None
            assert chunk.embedding_json.startswith("[")
