from datetime import UTC, datetime

from sqlalchemy import Column, Index, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class Game(SQLModel, table=True):
    __tablename__ = "games"

    id: int | None = Field(default=None, primary_key=True)
    appid: int = Field(index=True, unique=True)
    name: str
    type: str | None = None
    header_image: str | None = None
    last_resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    snapshots: list["GameSnapshot"] = Relationship(back_populates="game")


class GameAlias(SQLModel, table=True):
    __tablename__ = "game_aliases"
    __table_args__ = (
        UniqueConstraint("normalized_alias", "locale", name="uq_game_alias_locale"),
        Index("ix_game_aliases_appid_locale", "appid", "locale"),
    )

    id: int | None = Field(default=None, primary_key=True)
    appid: int = Field(index=True)
    canonical_name: str
    alias: str
    normalized_alias: str = Field(index=True)
    locale: str = Field(default="zh-CN", index=True, max_length=16)
    alias_type: str = Field(default="nickname", max_length=32)
    source: str = Field(default="user", max_length=32)
    confidence: float = 0.9
    notes: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GameSnapshot(SQLModel, table=True):
    __tablename__ = "game_snapshots"
    __table_args__ = (Index("ix_game_snapshots_appid_collected_at", "appid", "collected_at"),)

    id: int | None = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="games.id", index=True)
    appid: int = Field(index=True)
    collected_at: datetime = Field(default_factory=utc_now, index=True)
    source: str = "steam_public"
    cc: str
    language: str
    player_count: int | None = None
    is_free: bool | None = None
    currency: str | None = None
    initial_price: int | None = None
    final_price: int | None = None
    discount_percent: int | None = None
    recommendations_total: int | None = None
    raw_store_json: str = Field(default="{}", sa_column=Column(Text))
    raw_players_json: str = Field(default="{}", sa_column=Column(Text))
    raw_news_json: str = Field(default="{}", sa_column=Column(Text))
    source_urls_json: str = Field(default="{}", sa_column=Column(Text))

    game: Game = Relationship(back_populates="snapshots")
    labels: list["SnapshotLabel"] = Relationship(back_populates="snapshot")


class SnapshotLabel(SQLModel, table=True):
    __tablename__ = "snapshot_labels"
    __table_args__ = (UniqueConstraint("snapshot_id", "label", name="uq_snapshot_label"),)

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="game_snapshots.id", index=True)
    label: str = Field(index=True, max_length=80)
    created_at: datetime = Field(default_factory=utc_now)

    snapshot: GameSnapshot = Relationship(back_populates="labels")


class AnalysisReport(SQLModel, table=True):
    __tablename__ = "analysis_reports"

    id: int | None = Field(default=None, primary_key=True)
    query: str = Field(sa_column=Column(Text))
    answer_markdown: str = Field(sa_column=Column(Text))
    structured_result_json: str = Field(default="{}", sa_column=Column(Text))
    evidence_json: str = Field(default="[]", sa_column=Column(Text))
    snapshot_ids_json: str = Field(default="[]", sa_column=Column(Text))
    trace_id: str | None = Field(default=None, max_length=32, index=True)
    # Reproducibility metadata
    model: str | None = Field(default=None, max_length=64, description="LLM model used (e.g. deepseek-v4-pro)")
    prompt_version: str | None = Field(default=None, max_length=32, description="Hash of system prompt at generation time")
    tool_versions: str | None = Field(default=None, max_length=512, description="JSON map of tool_name → version hash")
    created_at: datetime = Field(default_factory=utc_now, index=True)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    user_key: str = Field(index=True, unique=True, max_length=128)
    display_name: str | None = None
    preferences_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    title: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str
    content: str = Field(sa_column=Column(Text))
    metadata_json: str = Field(default="{}", sa_column=Column(Text))
    trace_id: str | None = Field(default=None, max_length=32, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class ToolCall(SQLModel, table=True):
    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_conversation_created", "conversation_id", "created_at"),)

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int | None = Field(default=None, foreign_key="conversations.id", index=True)
    tool_name: str
    input_json: str = Field(default="{}", sa_column=Column(Text))
    output_summary: str = Field(default="", sa_column=Column(Text))
    status: str = "success"
    latency_ms: int | None = None
    trace_id: str | None = Field(default=None, max_length=32, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class MonitorTask(SQLModel, table=True):
    __tablename__ = "monitor_tasks"

    id: int | None = Field(default=None, primary_key=True)
    appid: int = Field(index=True)
    interval_minutes: int = 60
    enabled: bool = True
    last_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class MonitorAlert(SQLModel, table=True):
    __tablename__ = "monitor_alerts"

    id: int | None = Field(default=None, primary_key=True)
    appid: int = Field(index=True)
    snapshot_id: int
    alert_type: str
    summary: str = Field(sa_column=Column(Text))
    severity: str = "info"
    created_at: datetime = Field(default_factory=utc_now)


class ReviewAnalysis(SQLModel, table=True):
    __tablename__ = "review_analyses"
    __table_args__ = (Index("ix_review_analyses_appid_analyzed", "appid", "analyzed_at"),)

    id: int | None = Field(default=None, primary_key=True)
    appid: int = Field(index=True)
    total_reviews: int = 0
    positive_ratio: float | None = None
    top_praise_keywords_json: str = Field(default="[]", sa_column=Column(Text))
    top_complaint_keywords_json: str = Field(default="[]", sa_column=Column(Text))
    summary: str | None = Field(default=None, sa_column=Column(Text))
    source_url: str | None = None
    analyzed_at: datetime = Field(default_factory=utc_now)


class WebSource(SQLModel, table=True):
    __tablename__ = "web_sources"
    __table_args__ = (
        UniqueConstraint("source_url", "content_hash", name="uq_web_source_url_hash"),
        Index("ix_web_sources_game_fetched", "game_key", "fetched_at"),
        Index("ix_web_sources_appid_fetched", "appid", "fetched_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    game_key: str = Field(index=True, max_length=240)
    appid: int | None = Field(default=None, index=True)
    source_type: str = Field(default="web", index=True, max_length=40)
    source_url: str = Field(max_length=1000)
    title: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=240)
    published_at: datetime | None = Field(default=None, index=True)
    fetched_at: datetime = Field(default_factory=utc_now, index=True)
    raw_text: str = Field(default="", sa_column=Column(Text))
    excerpt: str = Field(default="", sa_column=Column(Text))
    content_hash: str = Field(index=True, max_length=64)
    metadata_json: str = Field(default="{}", sa_column=Column(Text))


class SentimentEvent(SQLModel, table=True):
    __tablename__ = "sentiment_events"
    __table_args__ = (
        Index("ix_sentiment_events_game_event_date", "game_key", "event_date"),
        Index("ix_sentiment_events_appid_event_date", "appid", "event_date"),
    )

    id: int | None = Field(default=None, primary_key=True)
    game_key: str = Field(index=True, max_length=240)
    appid: int | None = Field(default=None, index=True)
    event_date: datetime | None = Field(default=None, index=True)
    event_type: str = Field(default="web_sentiment", index=True, max_length=80)
    summary: str = Field(sa_column=Column(Text))
    sentiment: str = Field(default="mixed", index=True, max_length=32)
    severity: str = Field(default="medium", index=True, max_length=32)
    evidence_count: int = 0
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=utc_now, index=True)
    metadata_json: str = Field(default="{}", sa_column=Column(Text))


class SourceClaim(SQLModel, table=True):
    __tablename__ = "source_claims"
    __table_args__ = (Index("ix_source_claims_event_source", "event_id", "source_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="web_sources.id", index=True)
    event_id: int | None = Field(default=None, foreign_key="sentiment_events.id", index=True)
    claim_type: str = Field(default="player_feedback", index=True, max_length=80)
    claim_text: str = Field(sa_column=Column(Text))
    stance: str = Field(default="neutral", index=True, max_length=32)
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeDocument(SQLModel, table=True):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_appid_created", "appid", "created_at"),
        Index("ix_knowledge_documents_source", "source_type", "source_uri"),
    )

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True, max_length=240)
    source_type: str = Field(default="note", index=True, max_length=40)
    source_uri: str | None = Field(default=None, max_length=500)
    appid: int | None = Field(default=None, index=True)
    tags_json: str = Field(default="[]", sa_column=Column(Text))
    metadata_json: str = Field(default="{}", sa_column=Column(Text))
    content_hash: str = Field(index=True, max_length=64)
    chunk_count: int = 0
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_knowledge_chunk_document_ordinal"),
        Index("ix_knowledge_chunks_document", "document_id", "ordinal"),
    )

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="knowledge_documents.id", index=True)
    appid: int | None = Field(default=None, index=True)
    ordinal: int
    heading: str | None = Field(default=None, max_length=240)
    content: str = Field(sa_column=Column(Text))
    token_count: int = 0
    chunk_hash: str = Field(index=True, max_length=64)
    embedding_json: str = Field(default="[]", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now)


class MemoryEntry(SQLModel, table=True):
    """Cross-conversation memory entries with embeddings for semantic recall."""
    __tablename__ = "memory_entries"
    __table_args__ = (
        Index("ix_memory_entries_user_created", "user_id", "created_at"),
        Index("ix_memory_entries_user_appid", "user_id", "appid"),
        Index("ix_memory_entries_user_status_accessed", "user_id", "status", "last_accessed_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    conversation_id: int | None = Field(default=None, foreign_key="conversations.id", index=True)
    memory_type: str = Field(index=True, max_length=32)  # "fact" | "preference" | "summary" | "event"
    appid: int | None = Field(default=None, index=True)
    content: str = Field(sa_column=Column(Text))
    source_message_ids_json: str = Field(default="[]", sa_column=Column(Text))
    embedding_json: str = Field(default="[]", sa_column=Column(Text))
    content_hash: str = Field(index=True, max_length=64)
    importance: float = 0.5
    access_count: int = 0
    last_accessed_at: datetime | None = None
    status: str = Field(default="confirmed", max_length=20, index=True)
    confirmed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ConversationSummary(SQLModel, table=True):
    """Compressed summaries of message ranges within a conversation."""
    __tablename__ = "conversation_summaries"
    __table_args__ = (Index("ix_conversation_summaries_conv", "conversation_id", "created_at"),)

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    summary_text: str = Field(sa_column=Column(Text))
    message_range_start: int = 0
    message_range_end: int = 0
    embedding_json: str = Field(default="[]", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utc_now)


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str = Field(sa_column=Column(Text))
    updated_at: datetime = Field(default_factory=utc_now)


class BackgroundTask(SQLModel, table=True):
    """Async task queue for long-running operations.

    Tasks are enqueued by the API and picked up by a background worker.
    The frontend polls ``GET /tasks/{task_id}`` for status updates.
    """

    __tablename__ = "background_tasks"
    __table_args__ = (
        Index("ix_background_tasks_status_created", "status", "created_at"),
        Index("ix_background_tasks_user_created", "user_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    task_type: str = Field(
        index=True,
        max_length=40,
        description="Task kind: web_sentiment, report_generate, batch_snapshot, review_analyze",
    )
    status: str = Field(
        default="pending",
        index=True,
        max_length=20,
        description="pending | running | completed | failed | cancelled",
    )
    progress_pct: float = Field(default=0.0, ge=0, le=100, description="0–100 progress percentage")
    progress_message: str | None = Field(default=None, max_length=256, description="Human-readable progress status")
    input_json: str = Field(default="{}", sa_column=Column(Text))
    result_json: str = Field(default="{}", sa_column=Column(Text))
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    trace_id: str | None = Field(default=None, max_length=32, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class AgentRun(SQLModel, table=True):
    """Records of agent state-machine executions for recoverability.

    Each chat invocation creates one ``AgentRun``.  Each state transition
    within the run may create one or more ``AgentCheckpoint`` rows.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_conv_status", "conversation_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int | None = Field(default=None, foreign_key="conversations.id", index=True)
    trace_id: str | None = Field(default=None, max_length=32, index=True)
    state: str = Field(default="INIT", max_length=32, description="Last state (INIT/PLAN/ACT/…/DONE/ERROR)")
    status: str = Field(default="running", max_length=20, description="running | completed | failed | cancelled")
    input_query: str | None = Field(default=None, sa_column=Column(Text), description="User query that started this run")
    output_answer: str | None = Field(default=None, sa_column=Column(Text), description="Final answer (if completed)")
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    result_json: str = Field(default="{}", sa_column=Column(Text), description="Full AgentAnalysisResult JSON")
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AgentCheckpoint(SQLModel, table=True):
    """Per-state checkpoints within an AgentRun.

    Each state transition (PLAN → ACT, ACT → OBSERVE, etc.) records a
    checkpoint so failures can be diagnosed and, in future releases,
    long-running runs can be resumed from the last successful state.
    """

    __tablename__ = "agent_checkpoints"
    __table_args__ = (
        Index("ix_agent_checkpoints_run_state", "run_id", "state"),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="agent_runs.id", index=True)
    trace_id: str | None = Field(default=None, max_length=32, index=True)
    state: str = Field(max_length=32, description="State name: INIT, PLAN, ACT, OBSERVE, SYNTHESIZE, VALIDATE, DONE, ERROR")
    input_json: str = Field(default="{}", sa_column=Column(Text), description="Serialised state input")
    output_json: str = Field(default="{}", sa_column=Column(Text), description="Serialised state output")
    status: str = Field(default="success", max_length=20, description="success | error | skipped")
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
