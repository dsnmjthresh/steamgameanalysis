from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.web_sentiment import (
    SentimentEventRead,
    WebPageIngestRequest,
    WebSentimentReport,
    WebSentimentRequest,
    WebSourceRead,
)
from app.services.web_sentiment_service import WebSentimentService

router = APIRouter(prefix="/web-sentiment", tags=["web-sentiment"])


@router.post("/analyze", response_model=WebSentimentReport)
async def analyze_web_sentiment(
    payload: WebSentimentRequest,
    session: Session = Depends(get_session),
) -> WebSentimentReport:
    return await WebSentimentService().analyze(session, payload)


@router.post("/sources", response_model=WebSourceRead)
async def ingest_web_source(
    payload: WebPageIngestRequest,
    session: Session = Depends(get_session),
) -> WebSourceRead:
    try:
        return await WebSentimentService().ingest_url(
            session,
            url=str(payload.url),
            game=payload.game,
            appid=payload.appid,
            persist_to_knowledge=payload.persist_to_knowledge,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/events", response_model=list[SentimentEventRead])
def list_sentiment_events(
    game: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[SentimentEventRead]:
    return WebSentimentService().list_events(session, game=game, limit=limit)


@router.get("/sources", response_model=list[WebSourceRead])
def list_web_sources(
    game: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[WebSourceRead]:
    return WebSentimentService().list_sources(session, game=game, limit=limit)
