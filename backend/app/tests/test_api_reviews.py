"""Tests for /api/games/{appid}/reviews endpoints."""

import pytest
from sqlmodel import Session

from app.db.models import ReviewAnalysis


def _seed_review_analysis(session: Session, appid: int) -> ReviewAnalysis:
    import json

    analysis = ReviewAnalysis(
        appid=appid,
        total_reviews=100,
        positive_ratio=0.72,
        top_praise_keywords_json=json.dumps(["好玩", "画质好"]),
        top_complaint_keywords_json=json.dumps(["卡顿", "贵"]),
        summary="玩家总体评价良好，但对手感和价格有抱怨。",
        source_url="https://store.steampowered.com/app/730",
        reviews_json=json.dumps([]),
        language="schinese",
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


@pytest.mark.anyio
async def test_get_review_analysis_not_found(client):
    """GET /api/games/{appid}/reviews returns 404 when no analysis exists."""
    response = await client.get("/api/games/99999999/reviews")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_review_analysis_returns_result(client, session):
    """GET /api/games/{appid}/reviews returns sentiment analysis when it exists."""
    _seed_review_analysis(session, 730)

    response = await client.get("/api/games/730/reviews")

    assert response.status_code == 200
    body = response.json()
    assert body["appid"] == 730
    assert body["total_reviews"] == 100
    assert body["positive_ratio"] == 0.72
    assert "玩家" in body["summary"]


@pytest.mark.anyio
async def test_list_review_analyses_returns_history(client, session):
    """GET /api/games/{appid}/reviews/history returns list of past analyses."""
    _seed_review_analysis(session, 730)
    _seed_review_analysis(session, 730)

    response = await client.get("/api/games/730/reviews/history", params={"limit": 5})

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["appid"] == 730
