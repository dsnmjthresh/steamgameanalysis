from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, func, select

from app.db.models import KnowledgeChunk, KnowledgeDocument, utc_now
from app.schemas.knowledge import (
    KnowledgeChunkHit,
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeIndexStats,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)

RRF_K = 60
CHUNKING_POLICY = "python-function/markdown-heading/paragraph-window with overlap"
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9][a-zA-Z0-9_+#.\-]*")


@dataclass(frozen=True)
class _ChunkDraft:
    heading: str | None
    content: str
    token_count: int


@lru_cache(maxsize=1)
def _embedding_dim() -> int:
    """Return the current embedding dimension from the configured provider."""
    from app.services.embedding_service import get_embedding_service

    return get_embedding_service().dimension


def init_knowledge_indexes(engine: Engine) -> None:
    """Create optional retrieval indexes outside SQLModel's table metadata."""
    dim = _embedding_dim()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunk_fts
                USING fts5(
                    chunk_id UNINDEXED,
                    document_id UNINDEXED,
                    title,
                    heading,
                    content,
                    tokenize='unicode61'
                )
                """
            )
            if _sqlite_vec_available(connection):
                connection.exec_driver_sql(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_knowledge_chunks
                    USING vec0(embedding float[{dim}])
                    """
                )
    except SQLAlchemyError:
        # The app still works with Python-side fallback search if FTS/vector indexes are unavailable.
        return


def list_documents(session: Session, limit: int = 50) -> list[KnowledgeDocumentRead]:
    statement = (
        select(KnowledgeDocument)
        .order_by(KnowledgeDocument.updated_at.desc())  # type: ignore[attr-defined]
        .limit(max(1, min(limit, 200)))
    )  # type: ignore[attr-defined]
    return [_read_document(item) for item in session.exec(statement).all()]


def create_document(session: Session, payload: KnowledgeDocumentCreate) -> KnowledgeDocumentRead:
    """Create a knowledge document with its chunk embeddings.

    The entire operation runs inside a single database transaction: the
    document header is flushed (not committed) first to obtain an ID, then
    chunk embeddings are computed, and only after **all** embeddings succeed
    is the transaction committed.  If embedding fails at any point the
    transaction is rolled back, leaving no orphan document or partial chunks.
    """
    content = payload.content.strip()
    content_hash = _sha256(content)
    document = KnowledgeDocument(
        title=payload.title.strip(),
        source_type=payload.source_type.strip(),
        source_uri=payload.source_uri.strip() if payload.source_uri else None,
        appid=payload.appid,
        tags_json=json.dumps(_clean_tags(payload.tags), ensure_ascii=False),
        metadata_json=json.dumps(payload.metadata, ensure_ascii=False),
        content_hash=content_hash,
    )
    session.add(document)
    # Flush to obtain the auto-generated ID without committing — the
    # transaction stays open so we can roll back if embedding fails.
    session.flush()
    session.refresh(document)

    drafts = build_chunks(
        content,
        source_type=payload.source_type,
        chunk_size_tokens=payload.chunk_size_tokens,
        chunk_overlap_tokens=payload.chunk_overlap_tokens,
    )
    chunks: list[KnowledgeChunk] = []
    try:
        for ordinal, draft in enumerate(drafts):
            embedding = embed_text(f"{document.title}\n{draft.heading or ''}\n{draft.content}")
            chunk = KnowledgeChunk(
                document_id=document.id or 0,
                appid=payload.appid,
                ordinal=ordinal,
                heading=draft.heading,
                content=draft.content,
                token_count=draft.token_count,
                chunk_hash=_sha256(draft.content),
                embedding_json=json.dumps(embedding, separators=(",", ":")),
            )
            session.add(chunk)
            chunks.append(chunk)

        document.chunk_count = len(chunks)
        document.updated_at = utc_now()
        session.add(document)
        # Everything succeeded — commit the transaction.
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(document)
    for chunk in chunks:
        session.refresh(chunk)

    _index_chunks(session, document, chunks)
    return _read_document(document)


def delete_document(session: Session, document_id: int) -> None:
    document = session.get(KnowledgeDocument, document_id)
    if document is None:
        raise LookupError(f"knowledge document {document_id} was not found")
    chunks = session.exec(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).all()
    for chunk in chunks:
        if chunk.id is not None:
            _delete_index_row(session, chunk.id)
        session.delete(chunk)
    session.delete(document)
    session.commit()


def search_knowledge(session: Session, payload: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    keyword_candidates = _keyword_candidates(
        session,
        payload.query,
        limit=payload.keyword_limit,
        appid=payload.appid,
    )
    vector_candidates, vector_backend = _vector_candidates(
        session,
        payload.query,
        limit=payload.vector_limit,
        appid=payload.appid,
    )

    merged = _rrf_merge(keyword_candidates, vector_candidates)

    # Optional cross-encoder rerank (uses LLM when available, falls back silently)
    merged = _cross_encoder_rerank(payload.query, merged, session)

    hits = _rerank(session, payload.query, merged, appid=payload.appid)[: payload.limit]
    return KnowledgeSearchResponse(
        query=payload.query,
        hits=hits,
        debug={
            "keyword_candidates": len(keyword_candidates),
            "vector_candidates": len(vector_candidates),
            "vector_backend": vector_backend,
            "rrf_k": RRF_K,
            "chunking_policy": CHUNKING_POLICY,
        },
    )


def get_index_stats(session: Session) -> KnowledgeIndexStats:
    from app.services.embedding_service import get_embedding_service

    embedding_service = get_embedding_service()
    document_count = session.exec(select(func.count()).select_from(KnowledgeDocument)).one()
    chunk_count = session.exec(select(func.count()).select_from(KnowledgeChunk)).one()
    return KnowledgeIndexStats(
        documents=int(document_count or 0),
        chunks=int(chunk_count or 0),
        fts_enabled=_table_exists(session, "knowledge_chunk_fts"),
        sqlite_vec_enabled=_table_exists(session, "vec_knowledge_chunks") and _sqlite_vec_available(session),
        embedding_dim=_embedding_dim(),
        embedding_provider=embedding_service.name,
        semantic_capability=not embedding_service.name.startswith("hash"),
        chunking_policy=CHUNKING_POLICY,
    )


def build_chunks(
    content: str,
    source_type: str = "note",
    chunk_size_tokens: int = 700,
    chunk_overlap_tokens: int = 90,
) -> list[_ChunkDraft]:
    if source_type.lower() in {"python", "py", "code"}:
        code_chunks = _chunk_python_functions(content, chunk_size_tokens)
        if code_chunks:
            return code_chunks

    sections = _split_markdown_sections(content)
    chunks: list[_ChunkDraft] = []
    max_chars = chunk_size_tokens * 4
    overlap_chars = min(chunk_overlap_tokens * 4, max_chars // 3)
    for heading, section_text in sections:
        chunks.extend(_window_section(section_text, heading, max_chars=max_chars, overlap_chars=overlap_chars))
    return chunks or [_ChunkDraft(None, content.strip(), _estimate_tokens(content))]


def embed_text(text_value: str, dim: int | None = None) -> list[float]:
    """Embed a single text using the configured embedding provider.

    Delegates to ``embedding_service.embed_text_sync`` which bridges
    async API calls into synchronous code when needed.
    """
    from app.services.embedding_service import embed_text_sync as _embed

    return _embed(text_value, dim=dim)


def _read_document(item: KnowledgeDocument) -> KnowledgeDocumentRead:
    return KnowledgeDocumentRead(
        id=item.id or 0,
        title=item.title,
        source_type=item.source_type,
        source_uri=item.source_uri,
        appid=item.appid,
        tags=json.loads(item.tags_json or "[]"),
        metadata=json.loads(item.metadata_json or "{}"),
        content_hash=item.content_hash,
        chunk_count=item.chunk_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _chunk_python_functions(content: str, chunk_size_tokens: int) -> list[_ChunkDraft]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    lines = content.splitlines()
    chunks: list[_ChunkDraft] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end_lineno = getattr(node, "end_lineno", None)
        if end_lineno is None:
            continue
        start = max(node.lineno - 1, 0)
        end = min(end_lineno, len(lines))
        snippet = "\n".join(lines[start:end]).strip()
        if not snippet:
            continue
        heading = f"{type(node).__name__}:{node.name}"
        if _estimate_tokens(snippet) > chunk_size_tokens:
            chunks.extend(
                _window_section(snippet, heading, max_chars=chunk_size_tokens * 4, overlap_chars=chunk_size_tokens)
            )
        else:
            chunks.append(_ChunkDraft(heading, snippet, _estimate_tokens(snippet)))
    return chunks


def _split_markdown_sections(content: str) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    buffer: list[str] = []
    for line in content.splitlines():
        if line.lstrip().startswith("#"):
            if buffer:
                sections.append((heading, buffer))
                buffer = []
            heading = line.strip("# ").strip() or None
            continue
        buffer.append(line)
    if buffer:
        sections.append((heading, buffer))
    return [(heading, "\n".join(lines).strip()) for heading, lines in sections if "\n".join(lines).strip()]


def _window_section(
    text_value: str,
    heading: str | None,
    max_chars: int,
    overlap_chars: int,
) -> list[_ChunkDraft]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text_value) if item.strip()]
    chunks: list[_ChunkDraft] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current.strip():
                chunks.append(_ChunkDraft(heading, current.strip(), _estimate_tokens(current)))
                current = _overlap_tail(current, overlap_chars)
            for piece in _sliding_windows(paragraph, max_chars, overlap_chars):
                chunks.append(_ChunkDraft(heading, piece, _estimate_tokens(piece)))
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) > max_chars and current:
            chunks.append(_ChunkDraft(heading, current.strip(), _estimate_tokens(current)))
            current = f"{_overlap_tail(current, overlap_chars)}\n\n{paragraph}".strip()
        else:
            current = candidate
    if current.strip():
        chunks.append(_ChunkDraft(heading, current.strip(), _estimate_tokens(current)))
    return chunks


def _sliding_windows(text_value: str, max_chars: int, overlap_chars: int) -> list[str]:
    step = max(max_chars - overlap_chars, max_chars // 2, 1)
    pieces: list[str] = []
    start = 0
    while start < len(text_value):
        pieces.append(text_value[start : start + max_chars].strip())
        start += step
    return [item for item in pieces if item]


def _overlap_tail(text_value: str, overlap_chars: int) -> str:
    if overlap_chars <= 0:
        return ""
    return text_value[-overlap_chars:].strip()


def _keyword_candidates(
    session: Session,
    query: str,
    limit: int,
    appid: int | None,
) -> list[tuple[int, float]]:
    fts = _fts_candidates(session, query, limit=limit * 2)
    if fts:
        filtered = _filter_appid(session, fts, appid)
        if filtered:
            return filtered[:limit]
    return _python_keyword_candidates(session, query, limit=limit, appid=appid)


def _fts_candidates(session: Session, query: str, limit: int) -> list[tuple[int, float]]:
    if not _table_exists(session, "knowledge_chunk_fts"):
        return []
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    try:
        rows = session.execute(
            text(
                """
                SELECT chunk_id, bm25(knowledge_chunk_fts) AS rank_score
                FROM knowledge_chunk_fts
                WHERE knowledge_chunk_fts MATCH :query
                ORDER BY rank_score
                LIMIT :limit
                """
            ),
            {"query": fts_query, "limit": limit},
        ).mappings()
        return [(int(row["chunk_id"]), 1.0 / (abs(float(row["rank_score"])) + 1.0)) for row in rows]
    except SQLAlchemyError:
        return []


def _python_keyword_candidates(
    session: Session,
    query: str,
    limit: int,
    appid: int | None,
) -> list[tuple[int, float]]:
    terms = _query_terms(query)
    if not terms:
        return []
    statement = select(KnowledgeChunk)
    if appid is not None:
        statement = statement.where(KnowledgeChunk.appid == appid)
    chunks = session.exec(statement.limit(3000)).all()
    scored: list[tuple[int, float]] = []
    normalized_query = _normalize_text(query)
    for chunk in chunks:
        if chunk.id is None:
            continue
        haystack = _normalize_text(f"{chunk.heading or ''} {chunk.content}")
        overlap = sum(1 for term in terms if term in haystack)
        if overlap == 0 and normalized_query not in haystack:
            continue
        exact_bonus = 0.35 if normalized_query and normalized_query in haystack else 0
        score = overlap / max(len(terms), 1) + exact_bonus
        scored.append((chunk.id, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def _vector_candidates(
    session: Session,
    query: str,
    limit: int,
    appid: int | None,
) -> tuple[list[tuple[int, float]], str]:
    vector = embed_text(query)
    sqlite_vec = _sqlite_vec_candidates(session, vector, limit=limit * 2)
    if sqlite_vec:
        filtered = _filter_appid(session, sqlite_vec, appid)
        if filtered:
            return filtered[:limit], "sqlite-vec"
    return _python_vector_candidates(session, vector, limit=limit, appid=appid), "python-cosine"


def _sqlite_vec_candidates(
    session: Session,
    vector: list[float],
    limit: int,
) -> list[tuple[int, float]]:
    if not _table_exists(session, "vec_knowledge_chunks") or not _sqlite_vec_available(session):
        return []
    try:
        rows = session.execute(
            text(
                """
                SELECT rowid AS chunk_id, distance
                FROM vec_knowledge_chunks
                WHERE embedding MATCH :embedding
                ORDER BY distance
                LIMIT :limit
                """
            ),
            {"embedding": _serialize_float32(vector), "limit": limit},
        ).mappings()
        return [(int(row["chunk_id"]), 1.0 / (1.0 + float(row["distance"]))) for row in rows]
    except SQLAlchemyError:
        return []


def _python_vector_candidates(
    session: Session,
    query_vector: list[float],
    limit: int,
    appid: int | None,
) -> list[tuple[int, float]]:
    statement = select(KnowledgeChunk)
    if appid is not None:
        statement = statement.where(KnowledgeChunk.appid == appid)
    chunks = session.exec(statement.limit(3000)).all()
    scored: list[tuple[int, float]] = []
    for chunk in chunks:
        if chunk.id is None or not chunk.embedding_json:
            continue
        try:
            vector = json.loads(chunk.embedding_json)
        except json.JSONDecodeError:
            continue
        score = _cosine(query_vector, vector)
        if score > 0:
            scored.append((chunk.id, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def _cross_encoder_rerank(
    query: str,
    merged: dict[int, dict[str, float]],
    session: Session,
    top_k: int = 20,
) -> dict[int, dict[str, float]]:
    """Optional LLM-based cross-encoder reranking of top RRF candidates.

    Sends the top *top_k* chunks to the LLM for relevance scoring, then
    boosts the RRF score with the LLM relevance judgement.  Falls back
    silently to the original merged dict when the LLM is unavailable.
    """
    if len(merged) <= 6:
        return merged  # too few candidates to justify an LLM call

    try:
        from app.llm import create_chat_model_sync

        llm = create_chat_model_sync(temperature=0.0)
        if llm is None:
            return merged
    except Exception:
        return merged

    # Select top candidates to rerank
    sorted_items = sorted(merged.items(), key=lambda kv: kv[1]["score"], reverse=True)[:top_k]
    if len(sorted_items) <= 3:
        return merged

    # Build the scoring prompt
    chunks_text: list[str] = []
    id_map: dict[int, int] = {}  # label_index → chunk_id
    for idx, (chunk_id, _scores) in enumerate(sorted_items):
        chunk = session.get(KnowledgeChunk, chunk_id)
        if chunk is None:
            continue
        label = idx + 1
        id_map[label] = chunk_id
        doc = session.get(KnowledgeDocument, chunk.document_id)
        title = doc.title if doc else "unknown"
        chunks_text.append(
            f"[{label}] 标题: {title}\n"
            f"章节: {chunk.heading or '无'}\n"
            f"内容: {chunk.content[:500]}"
        )

    if len(chunks_text) < 2:
        return merged

    prompt = (
        "你是一个搜索相关性评估器。对于下面的查询，评估每个文档片段的相关性。\n"
        "只输出相关片段的编号（如 1,3,5），不要输出其他内容。\n\n"
        f"查询: {query}\n\n"
        + "\n\n".join(chunks_text)
        + "\n\n相关片段编号（用逗号分隔）:"
    )

    try:
        response = llm.invoke(prompt, temperature=0.0)
        text = str(getattr(response, "content", response)).strip()
        # Parse numbers from the response
        import re
        relevant_ids = {int(m) for m in re.findall(r"\d+", text) if 1 <= int(m) <= len(id_map)}
    except Exception:
        return merged

    if not relevant_ids:
        return merged

    # Boost scores of LLM-judged relevant chunks
    boost = 0.25
    for label, chunk_id in id_map.items():
        if label in relevant_ids:
            merged[chunk_id]["score"] += boost

    return merged


def _rrf_merge(
    keyword_candidates: list[tuple[int, float]],
    vector_candidates: list[tuple[int, float]],
) -> dict[int, dict[str, float]]:
    merged: dict[int, dict[str, float]] = defaultdict(lambda: {"score": 0.0, "keyword": 0.0, "vector": 0.0})
    for rank, (chunk_id, score) in enumerate(keyword_candidates, start=1):
        merged[chunk_id]["score"] += 1.2 / (RRF_K + rank)
        merged[chunk_id]["keyword"] = max(merged[chunk_id]["keyword"], score)
    for rank, (chunk_id, score) in enumerate(vector_candidates, start=1):
        merged[chunk_id]["score"] += 1.0 / (RRF_K + rank)
        merged[chunk_id]["vector"] = max(merged[chunk_id]["vector"], score)
    return dict(merged)


def _rerank(
    session: Session,
    query: str,
    merged: dict[int, dict[str, float]],
    appid: int | None,
) -> list[KnowledgeChunkHit]:
    terms = _query_terms(query)
    normalized_query = _normalize_text(query)
    hits: list[KnowledgeChunkHit] = []
    for chunk_id, scores in merged.items():
        chunk = session.get(KnowledgeChunk, chunk_id)
        if chunk is None or chunk.id is None:
            continue
        if appid is not None and chunk.appid != appid:
            continue
        document = session.get(KnowledgeDocument, chunk.document_id)
        if document is None:
            continue
        haystack = _normalize_text(f"{document.title} {chunk.heading or ''} {chunk.content}")
        overlap = sum(1 for term in terms if term in haystack)
        exact_bonus = 0.08 if normalized_query and normalized_query in haystack else 0
        title_bonus = 0.05 if any(term in _normalize_text(document.title) for term in terms) else 0
        heading_bonus = 0.04 if chunk.heading and any(term in _normalize_text(chunk.heading) for term in terms) else 0
        rerank_score = exact_bonus + title_bonus + heading_bonus + min(overlap * 0.015, 0.08)
        total = scores["score"] + rerank_score
        hits.append(
            KnowledgeChunkHit(
                chunk_id=chunk.id,
                document_id=document.id or 0,
                title=document.title,
                source_type=document.source_type,
                source_uri=document.source_uri,
                appid=chunk.appid,
                ordinal=chunk.ordinal,
                heading=chunk.heading,
                content=chunk.content,
                score=round(total, 6),
                keyword_score=round(scores["keyword"], 6),
                vector_score=round(scores["vector"], 6),
                rerank_score=round(rerank_score, 6),
            )
        )
    hits.sort(key=lambda item: item.score, reverse=True)
    return hits


def _index_chunks(session: Session, document: KnowledgeDocument, chunks: list[KnowledgeChunk]) -> None:
    for chunk in chunks:
        if chunk.id is None:
            continue
        _delete_index_row(session, chunk.id)
        try:
            session.execute(
                text(
                    """
                    INSERT INTO knowledge_chunk_fts
                    (rowid, chunk_id, document_id, title, heading, content)
                    VALUES (:rowid, :chunk_id, :document_id, :title, :heading, :content)
                    """
                ),
                {
                    "rowid": chunk.id,
                    "chunk_id": chunk.id,
                    "document_id": document.id,
                    "title": document.title,
                    "heading": chunk.heading or "",
                    "content": chunk.content,
                },
            )
        except SQLAlchemyError:
            pass
        _upsert_vector_row(session, chunk)
    session.commit()


def _upsert_vector_row(session: Session, chunk: KnowledgeChunk) -> None:
    if chunk.id is None or not _table_exists(session, "vec_knowledge_chunks") or not _sqlite_vec_available(session):
        return
    try:
        vector = json.loads(chunk.embedding_json)
        session.execute(
            text("INSERT OR REPLACE INTO vec_knowledge_chunks(rowid, embedding) VALUES (:rowid, :embedding)"),
            {"rowid": chunk.id, "embedding": _serialize_float32(vector)},
        )
    except (SQLAlchemyError, json.JSONDecodeError, TypeError, ValueError):
        return


def _delete_index_row(session: Session, chunk_id: int) -> None:
    try:
        if _table_exists(session, "knowledge_chunk_fts"):
            session.execute(text("DELETE FROM knowledge_chunk_fts WHERE rowid = :rowid"), {"rowid": chunk_id})
        if _table_exists(session, "vec_knowledge_chunks") and _sqlite_vec_available(session):
            session.execute(text("DELETE FROM vec_knowledge_chunks WHERE rowid = :rowid"), {"rowid": chunk_id})
    except SQLAlchemyError:
        return


def _filter_appid(
    session: Session,
    candidates: list[tuple[int, float]],
    appid: int | None,
) -> list[tuple[int, float]]:
    if appid is None:
        return candidates
    filtered: list[tuple[int, float]] = []
    for chunk_id, score in candidates:
        chunk = session.get(KnowledgeChunk, chunk_id)
        if chunk is not None and chunk.appid == appid:
            filtered.append((chunk_id, score))
    return filtered


def _sqlite_vec_available(connection_or_session: Any) -> bool:
    try:
        connection_or_session.execute(text("SELECT vec_version()")).scalar()
        return True
    except Exception:
        return False


def _table_exists(session: Session, table_name: str) -> bool:
    try:
        row = session.execute(
            text("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = :name"),
            {"name": table_name},
        ).first()
        return row is not None
    except SQLAlchemyError:
        return False


def _serialize_float32(vector: list[float]) -> bytes:
    try:
        from sqlite_vec import serialize_float32

        return serialize_float32(vector)  # type: ignore[no-any-return]
    except Exception:
        return struct.pack(f"<{len(vector)}f", *vector)


def _cosine(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size == 0:
        return 0
    dot = sum(left[index] * float(right[index]) for index in range(size))
    left_norm = math.sqrt(sum(left[index] * left[index] for index in range(size))) or 1.0
    right_norm = math.sqrt(sum(float(right[index]) * float(right[index]) for index in range(size))) or 1.0
    return max(0.0, dot / (left_norm * right_norm))


def _query_terms(text_value: str) -> list[str]:
    normalized = _normalize_text(text_value)
    terms = _TOKEN_RE.findall(normalized)
    if _CHINESE_RE.search(normalized) and len(normalized) <= 24:
        terms.append(normalized)
    return list(dict.fromkeys(term for term in terms if term))


def _fts_query(text_value: str) -> str:
    terms = _query_terms(text_value)[:8]
    return " OR ".join(f'"{term.replace("\"", "\"\"")}"' for term in terms)


def _normalize_text(text_value: str) -> str:
    lowered = text_value.lower().strip()
    return re.sub(r"[\s《》「」“”\"'’‘,，。.!！?？:：;；_\-—/\\]+", "", lowered)


def _estimate_tokens(text_value: str) -> int:
    chinese_chars = len(_CHINESE_RE.findall(text_value))
    latin_tokens = len(re.findall(r"[a-zA-Z0-9_+#.\-]+", text_value))
    return max(1, chinese_chars + latin_tokens)


def _clean_tags(tags: list[str]) -> list[str]:
    return [item.strip() for item in tags if item.strip()][:20]


def _sha256(text_value: str) -> str:
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()
