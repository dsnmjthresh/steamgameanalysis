import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.review import SentimentAnalysisResult
from app.services.review_service import ReviewService
from app.services.steam_client import SteamClient

router = APIRouter(prefix="/games/{appid}/reviews", tags=["reviews"])
logger = logging.getLogger("steamanalysis.reviews_api")


@router.get("", response_model=SentimentAnalysisResult)
def get_review_analysis(appid: int, session: Session = Depends(get_session)) -> SentimentAnalysisResult:
    result = ReviewService().latest_analysis(session, appid)
    if result is None:
        raise HTTPException(status_code=404, detail="review analysis was not found; run analyze first")
    return result


@router.post("/analyze", response_model=SentimentAnalysisResult)
async def analyze_reviews(
    appid: int,
    count: int = Query(
        default=100,
        ge=10,
        le=500,
        description="分析样本数。默认 100 以获得统计意义，最多 500。超过 100 会触发 LLM 批量分析",
    ),
    language: str = Query(
        default="schinese",
        description="评论语言过滤：schinese（简体中文）、english（英文）、tchinese（繁体中文）、japanese（日文）、koreana（韩文）",
    ),
    review_type: str = Query(
        default="all",
        pattern="^(all|positive|negative)$",
        description="评论类型过滤：all（全部）、positive（仅好评）、negative（仅差评）",
    ),
    days: int = Query(
        default=0,
        ge=0,
        le=365,
        description="时间窗口（天）。0 表示不限制，30 表示仅分析最近 30 天内的评论",
    ),
    session: Session = Depends(get_session),
) -> SentimentAnalysisResult:
    service = ReviewService()
    # Fetch more than requested to account for subsequent filtering
    fetch_count = count * 3 if (review_type != "all" or days > 0) else max(count, 100)
    fetch_count = min(fetch_count, 500)  # Steam API upper bound

    async with SteamClient() as steam:
        reviews, source_url, _ = await service.fetch_reviews(
            steam,
            appid=appid,
            count=fetch_count,
            language=language,
        )

    logger.info("Fetched %d reviews for appid %d (requested %d, type=%s, days=%d)",
                 len(reviews), appid, count, review_type, days)

    # Apply review_type filter
    if review_type == "positive":
        reviews = [r for r in reviews if r.voted_up]
    elif review_type == "negative":
        reviews = [r for r in reviews if not r.voted_up]

    # Apply time window filter
    if days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        reviews = [r for r in reviews if r.timestamp_created >= cutoff]
        logger.info("After %d-day filter: %d reviews remain", days, len(reviews))

    # Cap to requested count after filtering
    reviews = reviews[:count]

    if not reviews:
        return SentimentAnalysisResult(
            appid=appid,
            total_reviews=0,
            positive_ratio=0.0,
            summary=f"在指定条件下（type={review_type}, days={days}d）未找到可分析的评论。",
            source_url=None,
            analyzed_at=datetime.now(UTC),
            reviews=[],
        )

    # Use LLM-based analysis when available, with keyword fallback
    result = await service.analyze_sentiment_llm(
        appid=appid, reviews=reviews, source_url=source_url
    )
    service.save_analysis(session, result)

    # Add metadata about filtering to summary
    filter_notes = []
    if review_type != "all":
        filter_notes.append(f"仅{'好评' if review_type == 'positive' else '差评'}")
    if days > 0:
        filter_notes.append(f"最近 {days} 天")
    if filter_notes:
        result.summary = f"[{'，'.join(filter_notes)}] {result.summary}"

    return result


@router.get("/history", response_model=list[SentimentAnalysisResult])
def list_review_analyses(
    appid: int,
    limit: int = Query(default=5, ge=1, le=20),
    session: Session = Depends(get_session),
) -> list[SentimentAnalysisResult]:
    """List recent review analyses for an appid."""
    from sqlmodel import select

    from app.db.models import ReviewAnalysis
    from app.schemas.common import load_json

    rows = session.exec(
        select(ReviewAnalysis)
        .where(ReviewAnalysis.appid == appid)
        .order_by(ReviewAnalysis.analyzed_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    ).all()
    return [
        SentimentAnalysisResult(
            appid=row.appid,
            total_reviews=row.total_reviews,
            positive_ratio=row.positive_ratio or 0.0,
            top_praise_keywords=load_json(row.top_praise_keywords_json, []),
            top_complaint_keywords=load_json(row.top_complaint_keywords_json, []),
            summary=row.summary or "",
            source_url=row.source_url,
            analyzed_at=row.analyzed_at,
            reviews=[],
        )
        for row in rows
    ]
