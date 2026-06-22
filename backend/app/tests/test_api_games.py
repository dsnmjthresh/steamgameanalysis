"""Tests for /api/games endpoints — search, get, trend."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session

from app.db.models import Game
from app.schemas.game import GameCandidate, GameDetail, PriceInfo


def _seed_game(session: Session, appid: int, name: str) -> Game:
    game = Game(
        appid=appid,
        name=name,
        type="game",
        header_image="https://example.com/img.jpg",
    )
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


@pytest.mark.anyio
async def test_get_game_by_appid_returns_game(client, session):
    """GET /api/games/{appid} returns a GameRead from the database."""
    _seed_game(session, 730, "Counter-Strike 2")

    response = await client.get("/api/games/730")

    assert response.status_code == 200
    body = response.json()
    assert body["appid"] == 730
    assert body["name"] == "Counter-Strike 2"


@pytest.mark.anyio
async def test_get_game_not_found_fetches_from_steam(client):
    """GET /api/games/{appid} fetches from Steam API when not in DB."""
    now = datetime.now(UTC)

    mock_detail = GameDetail(
        appid=9999,
        name="Test Game",
        type="game",
        is_free=True,
        header_image="",
        genres=["Action"],
        categories=[],
        developers=[],
        publishers=[],
        recommendations_total=0,
        release_date="2025-01-01",
        price=PriceInfo(
            is_free=True,
            currency=None,
            initial_price=None,
            final_price=None,
            discount_percent=0,
            cc="CN",
            language="schinese",
        ),
        source_url="https://store.steampowered.com/",
        collected_at=now,
    )

    with patch(
        "app.api.routes.games.SteamClient",
        autospec=True,
    ) as mock_steam_cls:
        mock_instance = mock_steam_cls.return_value
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_instance.get_appdetails = AsyncMock(
            return_value=(
                {"730": {"data": {"name": "Test Game"}}},
                "https://store.steampowered.com/",
                now,
            )
        )
        mock_instance.normalize_appdetails = MagicMock(return_value=mock_detail)

        response = await client.get("/api/games/9999")

    # Should succeed with mocked Steam data
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Test Game"


@pytest.mark.anyio
async def test_search_games_returns_candidates(client):
    """GET /api/games/search returns game candidates."""
    mock_candidates = [
        GameCandidate(
            appid=730,
            name="Counter-Strike 2",
            type="game",
            confidence=0.99,
            source="steam",
            source_url="https://store.steampowered.com/app/730",
        )
    ]

    with patch(
        "app.api.routes.games.SteamClient",
        autospec=True,
    ) as mock_steam_cls:
        mock_instance = mock_steam_cls.return_value
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_instance.search_games = AsyncMock(return_value=mock_candidates)

        response = await client.get("/api/games/search", params={"query": "CS2"})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    if body:
        assert "appid" in body[0]
        assert "name" in body[0]


@pytest.mark.anyio
async def test_search_games_empty_query_rejects(client):
    """GET /api/games/search without query returns 422."""
    response = await client.get("/api/games/search")
    assert response.status_code == 422


@pytest.mark.anyio
async def test_game_trend_returns_analysis(client, session):
    """GET /api/games/{appid}/trend returns trend analysis."""
    _seed_game(session, 730, "Counter-Strike 2")

    response = await client.get("/api/games/730/trend", params={"days": 7})

    assert response.status_code == 200
    body = response.json()
    assert "appid" in body
    assert body["appid"] == 730
