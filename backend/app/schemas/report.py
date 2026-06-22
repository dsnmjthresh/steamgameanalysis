from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ReportRead(BaseModel):
    id: int
    query: str
    answer_markdown: str
    created_at: datetime
    snapshot_ids: list[int]
    model: str | None = None
    prompt_version: str | None = None
    tool_versions: dict[str, Any] | None = None
