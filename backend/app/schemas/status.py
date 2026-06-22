from pydantic import BaseModel, Field


class ComponentStatus(BaseModel):
    status: str = Field(description="ok | degraded | unavailable")
    detail: str | None = None


class RuntimeStatus(BaseModel):
    service: str
    version: str
    environment: str
    database: ComponentStatus
    vector_index: ComponentStatus
    llm: ComponentStatus
    embedding: ComponentStatus
    steam_api: ComponentStatus
    firecrawl: ComponentStatus
    scheduler: ComponentStatus
    task_worker: ComponentStatus
