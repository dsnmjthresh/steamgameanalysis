from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

# ---------------------------------------------------------------------------
# Fetch failure classification
# ---------------------------------------------------------------------------


class FetchFailureCategory(StrEnum):
    """Standardised fetch/scrape failure categories for metrics and logging."""

    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    EMPTY_CONTENT = "empty_content"
    PARSE_ERROR = "parse_error"
    SCHEME_DENIED = "scheme_denied"
    DOMAIN_DENIED = "domain_denied"
    PRIVATE_IP = "private_ip"
    LOCALHOST = "localhost"
    SPAM_DOMAIN = "spam_domain"
    REDIRECT_DENIED = "redirect_denied"


# ---------------------------------------------------------------------------
# Source policy result (read-only, for API / logging consumers)
# ---------------------------------------------------------------------------


class SourcePolicyResult(BaseModel):
    """Result of applying source governance rules to a URL."""

    url: str
    allowed: bool
    reason: str = ""
    failure_category: str | None = None
    domain: str = ""
    scheme: str = ""
    is_private_ip: bool = False
    is_localhost: bool = False
    is_spam_domain: bool = False


class WebSourceRead(BaseModel):
    id: int
    game_key: str
    appid: int | None = None
    source_type: str
    source_url: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    excerpt: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class SourceClaimRead(BaseModel):
    id: int
    source_id: int
    event_id: int | None = None
    claim_type: str
    claim_text: str
    stance: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}


class SentimentEventRead(BaseModel):
    id: int
    game_key: str
    appid: int | None = None
    event_date: datetime | None = None
    event_type: str
    summary: str
    sentiment: str
    severity: str
    evidence_count: int
    confidence: float
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class WebSentimentRequest(BaseModel):
    game: str | None = Field(default=None, max_length=200)
    query: str = Field(min_length=1, max_length=1000)
    appid: int | None = None
    event_date: datetime | None = None
    days_before: int = Field(default=7, ge=0, le=60)
    days_after: int = Field(default=7, ge=0, le=60)
    limit: int = Field(default=5, ge=1, le=10)
    persist_to_knowledge: bool = True


class WebPageIngestRequest(BaseModel):
    url: HttpUrl
    game: str | None = Field(default=None, max_length=200)
    appid: int | None = None
    persist_to_knowledge: bool = True


class WebSentimentReport(BaseModel):
    game_key: str
    appid: int | None = None
    query: str
    event_date: datetime | None = None
    summary: str
    sentiment: str
    severity: str
    confidence: float
    sources: list[WebSourceRead] = Field(default_factory=list)
    claims: list[SourceClaimRead] = Field(default_factory=list)
    event: SentimentEventRead | None = None
    search_queries: list[str] = Field(default_factory=list)
    source_backend: str = "none"
    uncertainties: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
