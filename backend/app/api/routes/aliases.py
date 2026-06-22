from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.game import GameAliasCreate, GameAliasRead, GameAliasResolveResult
from app.services.game_alias_service import (
    create_alias,
    delete_alias,
    list_aliases,
    resolve_aliases_in_text,
)

router = APIRouter(prefix="/aliases", tags=["aliases"])


@router.get("/games", response_model=list[GameAliasRead])
def read_game_aliases(
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[GameAliasRead]:
    return [GameAliasRead.model_validate(item) for item in list_aliases(session, query=query, limit=limit)]


@router.post("/games", response_model=GameAliasRead)
def create_game_alias(
    payload: GameAliasCreate,
    session: Session = Depends(get_session),
) -> GameAliasRead:
    return GameAliasRead.model_validate(create_alias(session, payload))


@router.delete("/games/{alias_id}", status_code=204)
def remove_game_alias(alias_id: int, session: Session = Depends(get_session)) -> None:
    try:
        delete_alias(session, alias_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/games/resolve", response_model=list[GameAliasResolveResult])
def resolve_game_aliases(
    text: str = Query(min_length=1),
    desired: int = Query(default=3, ge=1, le=10),
    session: Session = Depends(get_session),
) -> list[GameAliasResolveResult]:
    return resolve_aliases_in_text(session, text, desired=desired)
