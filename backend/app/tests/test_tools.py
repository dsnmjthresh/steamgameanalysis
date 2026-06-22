"""Tests for Agent tool execution — verify tool dispatch and output shapes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.tools import AgentToolContext, execute_tool
from app.services.steam_client import SteamClient


@pytest.fixture(name="tool_ctx")
def tool_ctx_fixture(session):
    """AgentToolContext with mocked SteamClient."""
    now = datetime.now(UTC)

    steam = AsyncMock(spec=SteamClient)
    steam.search_games = AsyncMock(return_value=[])
    steam.get_current_players = AsyncMock(
        return_value=(
            {"response": {"player_count": 1234567}},
            "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=730",
            now,
        )
    )

    # Create a proper Pydantic model mock for normalize_appdetails
    from app.schemas.game import GameDetail, PriceInfo

    mock_detail = GameDetail(
        appid=730,
        name="Counter-Strike 2",
        type="game",
        is_free=True,
        header_image="",
        genres=["Action"],
        categories=[],
        developers=[],
        publishers=[],
        recommendations_total=500000,
        release_date="2025-01-01",
        price=PriceInfo(
            is_free=True,
            currency="CNY",
            initial_price=0,
            final_price=0,
            discount_percent=0,
            cc="CN",
            language="schinese",
        ),
        source_url="https://store.steampowered.com/",
        collected_at=now,
    )
    steam.normalize_appdetails = MagicMock(return_value=mock_detail)
    steam.get_appdetails = AsyncMock(
        return_value=(
            {"730": {"data": {"name": "Counter-Strike 2", "is_free": True, "type": "game"}}},
            "https://store.steampowered.com/api/appdetails?appids=730",
            now,
        )
    )
    steam.get_game_news = AsyncMock(
        return_value=(
            [],
            "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=730",
            now,
        )
    )

    return AgentToolContext(session=session, steam=steam)


@pytest.mark.anyio
async def test_execute_search_games(tool_ctx):
    """execute_tool('search_games') returns query + candidates dict."""
    result = await execute_tool(tool_ctx, "search_games", query="CS2", limit=3)

    assert result["query"] == "CS2"
    assert "candidates" in result


@pytest.mark.anyio
async def test_execute_get_current_players(tool_ctx):
    """execute_tool('get_current_players') returns player_count."""
    result = await execute_tool(tool_ctx, "get_current_players", appid=730)

    assert result["appid"] == 730
    assert "player_count" in result
    assert "source_url" in result
    assert "collected_at" in result


@pytest.mark.anyio
async def test_execute_get_appdetails(tool_ctx):
    """execute_tool('get_appdetails') returns game detail dict."""
    result = await execute_tool(tool_ctx, "get_appdetails", appid=730)

    assert result["appid"] == 730
    assert "name" in result
    assert result["name"] == "Counter-Strike 2"


@pytest.mark.anyio
async def test_execute_get_game_news(tool_ctx):
    """execute_tool('get_game_news') returns appid + news list."""
    result = await execute_tool(tool_ctx, "get_game_news", appid=730)

    assert result["appid"] == 730
    assert "news" in result
    assert "source_url" in result
    assert "collected_at" in result


def test_execute_list_snapshots_empty(tool_ctx):
    """execute_tool('list_snapshots') returns empty list for no data."""
    from app.agent.tools import list_snapshots_tool

    result = list_snapshots_tool(tool_ctx, appid=730, limit=10)
    assert result["appid"] == 730
    assert "snapshots" in result


def test_execute_get_trend_analysis_empty(tool_ctx):
    """execute_tool('get_trend_analysis') returns trend for app with no snapshots."""
    from app.agent.tools import get_trend_analysis

    result = get_trend_analysis(tool_ctx, appid=730, days=7)
    assert result["appid"] == 730
    assert "summary" in result
