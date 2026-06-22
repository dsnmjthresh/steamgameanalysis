from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["L0", "L1", "L2", "L3", "L4"]
AgentTaskType = Literal[
    "single_game",
    "game_comparison",
    "review_analysis",
    "web_sentiment",
    "market_intelligence",
    "knowledge_qa",
    "history_trend",
    "schedule_monitor",
    "export",
    "unknown",
]


class AgentGameRef(BaseModel):
    appid: int
    name: str | None = None


class AgentEvidence(BaseModel):
    source: str
    url: str | None = None
    collected_at: datetime
    summary: str


class AgentToolStep(BaseModel):
    kind: Literal["thinking", "plan", "route", "tool_call", "observation", "result", "synthesize", "validate"] = "thinking"
    summary: str
    tool_name: str | None = None
    status: str = Field(
        default="pending",
        description="Step status: pending | running | success | failed | retry | skipped | blocked | warning",
    )
    detail: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ClarificationOption(BaseModel):
    """A candidate option presented to the user when the agent is uncertain."""
    label: str        # short label, e.g. "CS2 (appid 730)"
    description: str  # e.g. "第一人称射击游戏 Counter-Strike 2"
    action_query: str = ""  # suggested follow-up query when user selects this option


class AgentAnalysisResult(BaseModel):
    task_type: AgentTaskType | str = "single_game"
    classification_reason: str | None = None
    risk_level: RiskLevel = "L1"
    answer: str
    games: list[AgentGameRef] = Field(default_factory=list)
    evidence: list[AgentEvidence] = Field(default_factory=list)
    agent_steps: list[AgentToolStep] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    requires_human_confirmation: bool = False
    memory_used: bool = False
    memory_context_ids: list[int] = Field(default_factory=list)
    candidates: list[ClarificationOption] = Field(default_factory=list)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    auto_collect: bool = False  # default read-only; writes require explicit confirmation
    confirmed_write: bool = False  # user explicitly confirmed a write operation
    user_key: str | None = Field(default=None, max_length=128)


class ChatResponse(BaseModel):
    conversation_id: int
    report_id: int | None = None
    result: AgentAnalysisResult
