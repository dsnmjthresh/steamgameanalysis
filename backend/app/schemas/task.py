from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SupportedTaskType = Literal["web_sentiment", "batch_snapshot", "report_generate", "review_analyze"]
SUPPORTED_TASK_TYPES: tuple[str, ...] = ("web_sentiment", "batch_snapshot", "report_generate", "review_analyze")
BATCH_SNAPSHOT_APPIDS_LIMIT = 50


class TaskCreate(BaseModel):
    """Request to enqueue a background task."""

    task_type: SupportedTaskType = Field(
        description="Task type: web_sentiment, report_generate, batch_snapshot, review_analyze",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Task-specific parameters (appid, query, etc.)",
    )
    user_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_task_input(self) -> "TaskCreate":
        data = self.input_data
        if self.task_type == "web_sentiment":
            query = str(data.get("query") or "").strip()
            game = str(data.get("game") or "").strip()
            appid = data.get("appid")
            if not query and not game and appid is None:
                raise ValueError("web_sentiment requires query, game, or appid")
            limit = data.get("limit")
            if limit is not None and not _int_in_range(limit, 1, 10):
                raise ValueError("web_sentiment.limit must be between 1 and 10")

        if self.task_type == "batch_snapshot":
            appids = data.get("appids")
            if not isinstance(appids, list) or not appids:
                raise ValueError("batch_snapshot requires a non-empty appids list")
            if len(appids) > BATCH_SNAPSHOT_APPIDS_LIMIT:
                raise ValueError(f"batch_snapshot appids cannot exceed {BATCH_SNAPSHOT_APPIDS_LIMIT}")
            if any(not isinstance(item, int) or item <= 0 for item in appids):
                raise ValueError("batch_snapshot appids must be positive integers")

        if self.task_type == "report_generate":
            query = str(data.get("query") or "").strip()
            if not query:
                raise ValueError("report_generate requires query")
            appid = data.get("appid")
            if appid is not None and (not isinstance(appid, int) or appid <= 0):
                raise ValueError("report_generate.appid must be a positive integer when provided")

        if self.task_type == "review_analyze":
            appid = data.get("appid")
            if not isinstance(appid, int) or appid <= 0:
                raise ValueError("review_analyze requires a positive integer appid")
            count = data.get("count", 100)
            if not _int_in_range(count, 1, 500):
                raise ValueError("review_analyze.count must be between 1 and 500")
            review_type = data.get("review_type", "all")
            if review_type not in {"all", "positive", "negative"}:
                raise ValueError("review_analyze.review_type must be all, positive, or negative")
            days = data.get("days", 0)
            if not _int_in_range(days, 0, 365):
                raise ValueError("review_analyze.days must be between 0 and 365")
        return self


def _int_in_range(value: Any, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and minimum <= value <= maximum


class TaskRead(BaseModel):
    """Task status for frontend polling.

    Includes enriched error fields: ``error_code`` (machine-readable) and
    ``error_message`` (human-readable detail) — both derived from the single
    ``error_message`` database column without adding new schema fields.
    """

    id: int
    task_type: str
    status: str  # pending | running | completed | failed | cancelled
    progress_pct: float
    progress_message: str | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    result_data: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    error_code: str | None = Field(
        default=None,
        description="Machine-readable error code (e.g. STEAM_API_TIMEOUT, CANCELLED, UNKNOWN)",
    )
    trace_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
