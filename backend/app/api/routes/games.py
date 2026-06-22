from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.game import GameCandidate, GameDetail, GameRead
from app.schemas.snapshot import TrendAnalysis
from app.services.game_alias_service import resolve_aliases_in_text
from app.services.snapshot_service import analyze_snapshot_trend, get_game_by_appid, upsert_game
from app.services.steam_client import SteamClient, SteamClientError

router = APIRouter(prefix="/games", tags=["games"])


@router.get("/search", response_model=list[GameCandidate])
async def search_games(
    query: str = Query(min_length=1),
    cc: str | None = Query(default=None, min_length=2, max_length=2),
    language: str | None = None,
    session: Session = Depends(get_session),
) -> list[GameCandidate]:
    alias_matches = resolve_aliases_in_text(session, query, desired=5)
    alias_candidates = [
        GameCandidate(
            appid=item.appid,
            name=item.canonical_name,
            type="alias",
            confidence=item.confidence,
            source=f"本地游戏别名：{item.matched_alias}",
            source_url=f"local://game-aliases/{item.appid}",
        )
        for item in alias_matches
    ]
    async with SteamClient() as steam:
        steam_candidates = await steam.search_games(query=query, cc=cc, language=language)
    seen = {item.appid for item in alias_candidates}
    merged = [*alias_candidates, *[item for item in steam_candidates if item.appid not in seen]]
    return merged[:10]


@router.get("/{appid}/price-comparison", response_model=list[GameDetail])
async def price_comparison(
    appid: int,
    region: list[str] = Query(default=["CN:schinese", "US:english", "JP:japanese"]),
) -> list[GameDetail]:
    regions = [_parse_region(item) for item in region[:8]]
    async with SteamClient() as steam:
        try:
            return await steam.get_appdetails_multi_region(appid, regions)
        except SteamClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{appid}/trend", response_model=TrendAnalysis)
def game_trend(
    appid: int,
    days: int = Query(default=7, ge=1, le=365),
    session: Session = Depends(get_session),
) -> TrendAnalysis:
    return analyze_snapshot_trend(session, appid=appid, days=days)


@router.get("/{appid}", response_model=GameRead)
async def read_game(appid: int, session: Session = Depends(get_session)) -> GameRead:
    game = get_game_by_appid(session, appid)
    if game is not None:
        return GameRead.model_validate(game)

    async with SteamClient() as steam:
        try:
            data, source_url, collected_at = await steam.get_appdetails(appid)
            detail = steam.normalize_appdetails(appid, data, source_url, collected_at)
        except SteamClientError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    game = upsert_game(session, detail)
    return GameRead.model_validate(game)


def _parse_region(value: str) -> tuple[str, str]:
    if ":" in value:
        cc, language = value.split(":", 1)
        return cc.strip().upper(), language.strip() or "english"
    cc = value.strip().upper()
    default_language = "schinese" if cc == "CN" else "english"
    return cc, default_language
