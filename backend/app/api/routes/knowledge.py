from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeIndexStats,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.services.knowledge_service import (
    create_document,
    delete_document,
    get_index_stats,
    list_documents,
    search_knowledge,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/documents", response_model=list[KnowledgeDocumentRead])
def read_documents(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[KnowledgeDocumentRead]:
    return list_documents(session, limit=limit)


@router.post("/documents", response_model=KnowledgeDocumentRead)
def create_knowledge_document(
    payload: KnowledgeDocumentCreate,
    session: Session = Depends(get_session),
) -> KnowledgeDocumentRead:
    return create_document(session, payload)


@router.delete("/documents/{document_id}", status_code=204)
def remove_knowledge_document(document_id: int, session: Session = Depends(get_session)) -> None:
    try:
        delete_document(session, document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge_base(
    payload: KnowledgeSearchRequest,
    session: Session = Depends(get_session),
) -> KnowledgeSearchResponse:
    return search_knowledge(session, payload)


@router.get("/stats", response_model=KnowledgeIndexStats)
def knowledge_stats(session: Session = Depends(get_session)) -> KnowledgeIndexStats:
    return get_index_stats(session)
