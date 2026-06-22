from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1)
    source_type: str = Field(default="note", min_length=1, max_length=40)
    source_uri: str | None = Field(default=None, max_length=500)
    appid: int | None = Field(default=None, gt=0)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_size_tokens: int = Field(default=700, ge=180, le=1600)
    chunk_overlap_tokens: int = Field(default=90, ge=0, le=400)


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source_type: str
    source_uri: str | None = None
    appid: int | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    appid: int | None = None
    ordinal: int
    heading: str | None = None
    content: str
    token_count: int
    chunk_hash: str
    created_at: datetime


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    appid: int | None = Field(default=None, gt=0)
    limit: int = Field(default=6, ge=1, le=20)
    keyword_limit: int = Field(default=40, ge=1, le=120)
    vector_limit: int = Field(default=40, ge=1, le=120)


class KnowledgeChunkHit(BaseModel):
    chunk_id: int
    document_id: int
    title: str
    source_type: str
    source_uri: str | None = None
    appid: int | None = None
    ordinal: int
    heading: str | None = None
    content: str
    score: float
    keyword_score: float = 0
    vector_score: float = 0
    rerank_score: float = 0


class KnowledgeSearchResponse(BaseModel):
    query: str
    hits: list[KnowledgeChunkHit]
    debug: dict[str, Any] = Field(default_factory=dict)


class KnowledgeIndexStats(BaseModel):
    documents: int
    chunks: int
    fts_enabled: bool
    sqlite_vec_enabled: bool
    embedding_dim: int
    embedding_provider: str
    semantic_capability: bool
    chunking_policy: str
