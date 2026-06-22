from datetime import datetime

from pydantic import BaseModel, Field


class ReviewItem(BaseModel):
    review_id: str
    author: str | None = None
    voted_up: bool
    review_text: str
    playtime_forever: int = 0
    language: str
    timestamp_created: datetime


class SentimentAnalysisResult(BaseModel):
    appid: int
    total_reviews: int
    positive_ratio: float = Field(ge=0, le=1)
    top_praise_keywords: list[str] = Field(default_factory=list)
    top_complaint_keywords: list[str] = Field(default_factory=list)
    summary: str
    source_url: str | None = None
    analyzed_at: datetime
    reviews: list[ReviewItem] = Field(default_factory=list)
