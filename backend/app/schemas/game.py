from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GameCandidate(BaseModel):
    appid: int
    name: str
    type: str | None = None
    confidence: float = Field(ge=0, le=1)
    source: str
    source_url: str


class PriceInfo(BaseModel):
    is_free: bool | None = None
    currency: str | None = None
    initial_price: int | None = None
    final_price: int | None = None
    discount_percent: int | None = None
    formatted_initial_price: str | None = None
    formatted_final_price: str | None = None
    cc: str
    language: str


class NewsItem(BaseModel):
    title: str
    url: str | None = None
    published_at: datetime | None = None
    summary: str | None = None


class GameDetail(BaseModel):
    appid: int
    name: str
    type: str | None = None
    header_image: str | None = None
    is_free: bool | None = None
    release_date: str | None = None
    developers: list[str] = Field(default_factory=list)
    publishers: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    recommendations_total: int | None = None
    price: PriceInfo | None = None
    source_url: str
    collected_at: datetime


class GameRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appid: int
    name: str
    type: str | None = None
    header_image: str | None = None
    last_resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class GameAliasCreate(BaseModel):
    appid: int = Field(gt=0)
    canonical_name: str = Field(min_length=1, max_length=200)
    alias: str = Field(min_length=1, max_length=120)
    locale: str = Field(default="zh-CN", min_length=2, max_length=16)
    alias_type: str = Field(default="nickname", min_length=1, max_length=32)
    source: str = Field(default="user", min_length=1, max_length=32)
    confidence: float = Field(default=0.9, ge=0, le=1)
    notes: str | None = Field(default=None, max_length=500)


class GameAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appid: int
    canonical_name: str
    alias: str
    normalized_alias: str
    locale: str
    alias_type: str
    source: str
    confidence: float
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class GameAliasResolveResult(BaseModel):
    appid: int
    canonical_name: str
    matched_alias: str
    confidence: float
    source: str
