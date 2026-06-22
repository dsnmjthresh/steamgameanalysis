"""Tests for /api/chat endpoints — non-streaming and streaming."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.schemas.chat import (
    AgentAnalysisResult,
    AgentEvidence,
    AgentGameRef,
    AgentToolStep,
)

_AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _patched_settings() -> Settings:
    """Settings with auth token configured for tests."""
    return Settings(auth_token="test-token")


def _make_stub_result(**overrides) -> AgentAnalysisResult:
    kwargs = {
        "task_type": "single_game",
        "answer": "Counter-Strike 2 当前在线玩家约 120 万，近期无价格变动。",
        "games": [AgentGameRef(appid=730, name="Counter-Strike 2")],
        "evidence": [
            AgentEvidence(
                source="Steam API",
                url="https://store.steampowered.com/api/appdetails?appids=730",
                collected_at=datetime.fromisoformat("2025-01-01T00:00:00+00:00"),  # type: ignore[arg-type]
                summary="实时玩家数据",
            )
        ],
        "agent_steps": [
            AgentToolStep(kind="route", summary="分类为 single_game", status="success"),
        ],
        "assumptions": [],
        "uncertainties": [],
        "recommended_next_steps": [],
        **overrides,
    }
    return AgentAnalysisResult(**kwargs)


@pytest.mark.anyio
async def test_chat_non_streaming_returns_result(client):
    """POST /api/chat returns ChatResponse with conversation_id and result."""
    with (
        patch("app.api.routes.chat.answer",
            new=AsyncMock(
                return_value=(
                    type("Conversation", (), {"id": 1})(),
                    type("Report", (), {"id": 5})(),
                    _make_stub_result(),
                )
            ),
        ),
        patch("app.core.config.get_settings", return_value=_patched_settings()),
    ):
        response = await client.post(
            "/api/chat",
            json={"query": "CS2 现在有多少玩家在线？"},
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == 1
    assert body["report_id"] == 5
    assert "result" in body
    assert body["result"]["task_type"] == "single_game"
    assert "CS2" in body["result"]["answer"] or "Counter-Strike 2" in body["result"]["answer"]


@pytest.mark.anyio
async def test_chat_empty_query_rejects(client):
    """POST /api/chat with empty query returns 422 validation error."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/chat",
            json={"query": ""},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_chat_missing_query_rejects(client):
    """POST /api/chat without query field returns 422."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/chat",
            json={},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_chat_streaming_returns_sse_events(client):
    """POST /api/chat/stream returns SSE event stream with result event."""
    with (
        patch("app.api.routes.chat.answer",
            new=AsyncMock(
                return_value=(
                    type("Conversation", (), {"id": 1})(),
                    type("Report", (), {"id": 5})(),
                    _make_stub_result(),
                )
            ),
        ),
        patch("app.core.config.get_settings", return_value=_patched_settings()),
    ):
        response = await client.post(
            "/api/chat/stream",
            json={"query": "CS2 现在有多少玩家在线？"},
            headers={"Accept": "text/event-stream", **_AUTH_HEADERS},
        )

    assert response.status_code == 200
    text = response.text
    assert "event:" in text
    assert "data:" in text


@pytest.mark.anyio
async def test_chat_with_auto_collect_flag(client):
    """POST /api/chat with auto_collect=True is accepted."""
    with (
        patch("app.api.routes.chat.answer",
            new=AsyncMock(
                return_value=(
                    type("Conversation", (), {"id": 2})(),
                    None,
                    _make_stub_result(task_type="single_game"),
                )
            ),
        ),
        patch("app.core.config.get_settings", return_value=_patched_settings()),
    ):
        response = await client.post(
            "/api/chat",
            json={"query": "保存所有游戏快照", "auto_collect": True},
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == 2
