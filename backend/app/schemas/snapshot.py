from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import GameSnapshot
from app.schemas.common import as_utc, load_json
from app.schemas.game import NewsItem


class SnapshotCreateRequest(BaseModel):
    cc: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = None
    labels: list[str] = Field(default_factory=list, max_length=8)


class SnapshotLabelCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class SnapshotLabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    snapshot_id: int
    label: str
    created_at: datetime


class SnapshotRead(BaseModel):
    id: int
    game_id: int
    appid: int
    collected_at: datetime
    source: str
    cc: str
    language: str
    player_count: int | None = None
    is_free: bool | None = None
    currency: str | None = None
    initial_price: int | None = None
    final_price: int | None = None
    discount_percent: int | None = None
    recommendations_total: int | None = None
    labels: list[str] = Field(default_factory=list)
    source_urls: dict[str, str] = Field(default_factory=dict)
    news: list[NewsItem] = Field(default_factory=list)

    @classmethod
    def from_model(cls, snapshot: GameSnapshot) -> "SnapshotRead":
        return cls(
            id=snapshot.id or 0,
            game_id=snapshot.game_id,
            appid=snapshot.appid,
            collected_at=as_utc(snapshot.collected_at),
            source=snapshot.source,
            cc=snapshot.cc,
            language=snapshot.language,
            player_count=snapshot.player_count,
            is_free=snapshot.is_free,
            currency=snapshot.currency,
            initial_price=snapshot.initial_price,
            final_price=snapshot.final_price,
            discount_percent=snapshot.discount_percent,
            recommendations_total=snapshot.recommendations_total,
            labels=[label.label for label in snapshot.labels],
            source_urls=load_json(snapshot.source_urls_json, {}),
            news=[NewsItem(**item) for item in load_json(snapshot.raw_news_json, [])],  # type: ignore[var-annotated]
        )


class TrendPriceChange(BaseModel):
    snapshot_id: int
    collected_at: datetime
    previous_price: int
    current_price: int
    currency: str | None = None


class TrendAnalysis(BaseModel):
    appid: int
    days: int
    snapshot_count: int
    player_count_trend: str
    player_count_peak: int | None = None
    player_count_avg: int | None = None
    price_changes: list[TrendPriceChange] = Field(default_factory=list)
    summary: str
    recommendation: str | None = None
    snapshots: list[SnapshotRead] = Field(default_factory=list)
