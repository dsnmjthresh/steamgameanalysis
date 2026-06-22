"""Agent tools with strict Pydantic schemas.

Each tool now declares:
- Explicit input model (Pydantic) with descriptions, enums, bounds, and units
- Output model or return-type documentation
- Permission level (read / write / confirm)
- Timeout (seconds)
- Retry policy (max_retries, retry_delay_s, retry_on status codes)
- Error codes

Schema is no longer auto-generated from function signatures — every field carries
a human-written description usable by the LLM for tool selection.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.logging import get_request_id
from app.db.models import ToolCall
from app.schemas.common import dump_json
from app.schemas.compare import CompareTarget
from app.schemas.snapshot import SnapshotRead
from app.services.comparison_service import compare_snapshots
from app.services.knowledge_service import search_knowledge
from app.services.review_service import ReviewService
from app.services.snapshot_service import (
    add_snapshot_label,
    analyze_snapshot_trend,
    collect_snapshot,
    list_snapshots,
)
from app.services.steam_client import SteamClient
from app.services.web_sentiment_service import WebSentimentService

# ══════════════════════════════════════════════════════════════════════════════
# Enums & shared types
# ══════════════════════════════════════════════════════════════════════════════

Permission = Literal["read", "write", "confirm"]
ToolFunction = Callable[..., Awaitable[Any] | Any]


class RetryPolicy(BaseModel):
    max_retries: int = Field(default=2, ge=0, le=5, description="最大重试次数")
    delay_s: float = Field(default=1.0, ge=0.1, le=30.0, description="重试间隔（秒）")
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=5.0, description="退避倍率")
    retry_on: list[str] = Field(
        default_factory=lambda: ["timeout", "rate_limit", "server_error"],
        description="触发重试的错误类型",
    )


class ToolErrorCode(StrEnum):
    """Standardised error codes returned by tools."""

    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ReviewType(StrEnum):
    all = "all"
    positive = "positive"
    negative = "negative"


class ReviewLanguage(StrEnum):
    schinese = "schinese"
    english = "english"
    tchinese = "tchinese"
    japanese = "japanese"
    koreana = "koreana"


@dataclass(frozen=True)
class AgentToolContext:
    session: Session
    steam: SteamClient
    conversation_id: int | None = None
    confirmed_write: bool = False
    confirmation_token: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    permissions: Permission
    function: ToolFunction
    schema: dict[str, Any]
    # New strict-schema fields
    input_model: type[BaseModel] | None = None
    output_description: str = ""
    error_codes: list[ToolErrorCode] = field(default_factory=list)
    timeout_s: float = 15.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)


_tool_registry: dict[str, ToolDefinition] = {}


# ══════════════════════════════════════════════════════════════════════════════
# Strict Pydantic input models for every tool
# ══════════════════════════════════════════════════════════════════════════════

class SearchGamesInput(BaseModel):
    """Search Steam games by name and return candidate appids."""

    query: str = Field(
        min_length=1,
        max_length=200,
        description="游戏名称或关键词，支持中英文。如 'CS2'、'艾尔登法环'、'Elden Ring'",
        examples=["CS2", "黑神话悟空"],
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="返回候选数量上限",
    )


class GetCurrentPlayersInput(BaseModel):
    """Get current player count for a Steam app."""

    appid: int = Field(
        ge=1,
        le=9_999_999,
        description="Steam 应用 ID。如 CS2 为 730，Dota 2 为 570",
        examples=[730, 570],
    )


class GetAppDetailsInput(BaseModel):
    """Get game store page details including price, discount, genres, etc."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    cc: str | None = Field(
        default=None,
        max_length=4,
        description="ISO 国家代码，影响价格和地区。如 'CN', 'US', 'JP'。不传则使用默认配置",
        examples=["CN", "US"],
    )
    language: str | None = Field(
        default=None,
        max_length=16,
        description="返回内容的语言代码。如 'schinese', 'english'",
    )


class GetGameNewsInput(BaseModel):
    """Get recent Steam news for a game."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    count: int = Field(default=5, ge=1, le=20, description="返回新闻条数")


class GetAchievementStatsInput(BaseModel):
    """Get global achievement completion percentages."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    limit: int = Field(default=10, ge=1, le=100, description="返回成就数量上限")


class ListSnapshotsInput(BaseModel):
    """List local historical snapshots for a given appid."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    limit: int = Field(default=10, ge=1, le=100, description="返回快照数量上限")


class CompareSnapshotsInput(BaseModel):
    """Compare two local snapshots side-by-side."""

    left_snapshot_id: int = Field(ge=1, description="左侧/较早的快照 ID")
    right_snapshot_id: int = Field(ge=1, description="右侧/较新的快照 ID")


class SaveSnapshotInput(BaseModel):
    """Collect and persist a current game data snapshot to the local database."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    cc: str | None = Field(default=None, max_length=4, description="ISO 国家代码")
    language: str | None = Field(default=None, max_length=16, description="语言代码")


class LabelSnapshotInput(BaseModel):
    """Add a human-readable label to a snapshot."""

    snapshot_id: int = Field(ge=1, description="目标快照 ID")
    label: str = Field(min_length=1, max_length=80, description="标签文本，如 '更新前'、'大促期间'")


class GetReviewsInput(BaseModel):
    """Fetch Steam user reviews for a game."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    count: int = Field(default=20, ge=1, le=500, description="获取评论数量。统计显著性建议 ≥100")
    language: str = Field(
        default="schinese",
        description="评论语言过滤。'schinese' 简体中文，'english' 英文，'all' 全部语言",
    )


class AnalyzeReviewsInput(BaseModel):
    """Analyze Steam reviews for sentiment, keywords, and topic extraction."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    count: int = Field(
        default=100,
        ge=10,
        le=500,
        description="分析评论样本数。默认 100 条以获得统计意义，最多 500 条",
    )
    review_type: ReviewType = Field(
        default=ReviewType.all,
        description="评论过滤类型：all 全部，positive 仅好评，negative 仅差评",
    )
    language: str = Field(
        default="schinese",
        description="评论语言过滤",
    )
    days: int = Field(
        default=0,
        ge=0,
        le=365,
        description="时间窗口（天）。0 表示不限制，30 表示仅分析最近 30 天内的评论",
    )


class GetTrendAnalysisInput(BaseModel):
    """Analyze historical snapshot trends for a game."""

    appid: int = Field(ge=1, le=9_999_999, description="Steam 应用 ID")
    days: int = Field(default=7, ge=1, le=365, description="分析时间跨度（天）")


class RagSearchInput(BaseModel):
    """Hybrid keyword + vector search in the local knowledge base."""

    query: str = Field(min_length=1, max_length=1000, description="搜索查询文本")
    appid: int | None = Field(default=None, ge=1, le=9_999_999, description="限定游戏 appid（可选）")
    limit: int = Field(default=6, ge=1, le=20, description="返回结果数量")


class AnalyzeWebSentimentInput(BaseModel):
    """Search public web and analyze community sentiment for a game."""

    query: str = Field(
        min_length=1,
        max_length=500,
        description="搜索查询。如 'CS2 更新后玩家不满'",
    )
    game: str | None = Field(
        default=None,
        max_length=200,
        description="游戏名称（可选，用于构造搜索词）",
    )
    appid: int | None = Field(default=None, ge=1, le=9_999_999, description="关联的 Steam appid（可选）")
    limit: int = Field(default=5, ge=1, le=15, description="最大搜索/抓取结果数")


class RecallMemoryInput(BaseModel):
    """Search user conversation memory for previously discussed facts."""

    query: str = Field(min_length=1, max_length=500, description="要搜索的记忆关键词或语义查询")
    limit: int = Field(default=5, ge=1, le=20, description="返回记忆条数上限")


# ══════════════════════════════════════════════════════════════════════════════
# Tool registration
# ══════════════════════════════════════════════════════════════════════════════


def register_tool(
    name: str,
    description: str,
    permissions: Permission = "read",
    *,
    input_model: type[BaseModel] | None = None,
    output_description: str = "",
    error_codes: list[ToolErrorCode] | None = None,
    timeout_s: float = 15.0,
    retry_policy: RetryPolicy | None = None,
):
    def decorator(func: ToolFunction) -> ToolFunction:
        _tool_registry[name] = ToolDefinition(
            name=name,
            description=description,
            permissions=permissions,
            function=func,
            schema=_schema_from_signature(func),
            input_model=input_model,
            output_description=output_description,
            error_codes=error_codes or [ToolErrorCode.INTERNAL_ERROR],
            timeout_s=timeout_s,
            retry_policy=retry_policy or RetryPolicy(),
        )
        return func

    return decorator


def list_registered_tools() -> list[ToolDefinition]:
    return list(_tool_registry.values())


def get_tool_registry() -> dict[str, ToolDefinition]:
    return dict(_tool_registry)


async def execute_tool(ctx: AgentToolContext, name: str, **kwargs: Any) -> Any:
    """Execute a registered tool with unified policy enforcement.

    Enforces (in order):
    1. Input schema validation (Pydantic input_model)
    2. Permission check (read / write / confirm)
    3. Timeout (definition.timeout_s)
    4. Retry (definition.retry_policy)
    5. Audit logging (ToolCall with permission, retry_count, error_code)

    Raises ``PermissionError`` when a write tool is called without confirmation.
    """
    definition = _tool_registry.get(name)
    if definition is None:
        raise ValueError(f"Tool '{name}' not registered")

    # ── 1. Input validation ──────────────────────────────────────────────
    if definition.input_model is not None:
        try:
            validated = definition.input_model(**kwargs)
            kwargs = validated.model_dump()
        except Exception as exc:
            _audit_tool_call(ctx, name, kwargs, "invalid_input", 0, str(exc)[:500])
            raise ValueError(f"Tool '{name}' input validation failed: {exc}") from exc

    # ── 2. Permission check ──────────────────────────────────────────────
    error_code: str | None = None
    if definition.permissions == "confirm":
        # Confirm tools return a confirmation result rather than executing
        result = {
            "requires_confirmation": True,
            "tool": name,
            "message": f"Tool '{name}' requires explicit confirmation before execution.",
        }
        _audit_tool_call(ctx, name, kwargs, "confirm_required", 0, "")
        return result

    if definition.permissions == "write":
        if not ctx.confirmed_write and not ctx.confirmation_token:
            _audit_tool_call(ctx, name, kwargs, "permission_denied", 0,
                             "Write tool called without confirmation")
            raise PermissionError(
                f"Tool '{name}' requires write confirmation. "
                "Set confirmed_write=True or provide a confirmation_token."
            )

    # ── 3. Execute with timeout + retry ──────────────────────────────────
    retry_policy = definition.retry_policy
    last_exception: Exception | None = None
    started = time.perf_counter()

    for attempt in range(retry_policy.max_retries + 1):
        try:
            result = await _execute_with_timeout(definition, ctx, kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            _audit_tool_call(ctx, name, kwargs, "success", attempt,
                             _summarize_result(result), latency_ms)
            return result
        except TimeoutError:
            error_code = ToolErrorCode.TIMEOUT.value
            last_exception = TimeoutError(f"Tool '{name}' timed out after {definition.timeout_s}s")
            if not _should_retry(retry_policy, "timeout", attempt):
                break
            await asyncio.sleep(retry_policy.delay_s * (retry_policy.backoff_multiplier ** attempt))
        except Exception as exc:
            error_code = _classify_error(exc)
            last_exception = exc
            if not _should_retry(retry_policy, error_code, attempt):
                break
            await asyncio.sleep(retry_policy.delay_s * (retry_policy.backoff_multiplier ** attempt))

    # All retries exhausted
    latency_ms = int((time.perf_counter() - started) * 1000)
    error_msg = str(last_exception) if last_exception else "Unknown error"
    _audit_tool_call(ctx, name, kwargs, error_code or "error",
                     retry_policy.max_retries, error_msg[:500], latency_ms)
    raise last_exception  # type: ignore[misc]


async def _execute_with_timeout(
    definition: ToolDefinition,
    ctx: AgentToolContext,
    kwargs: dict[str, Any],
) -> Any:
    """Execute a tool function with a timeout wrapper."""
    import asyncio as _asyncio

    func = definition.function
    result = func(ctx, **kwargs)
    if inspect.isawaitable(result):
        result = await _asyncio.wait_for(result, timeout=definition.timeout_s)
    return result


def _should_retry(policy: RetryPolicy, error_code: str, attempt: int) -> bool:
    """Check whether a retry should be attempted."""
    if attempt >= policy.max_retries:
        return False
    return error_code in policy.retry_on


def _classify_error(exc: Exception) -> str:
    """Map an exception to a standardised error code string."""
    import asyncio as _asyncio

    if isinstance(exc, _asyncio.TimeoutError):
        return "timeout"
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg:
        return "rate_limit"
    if "server error" in msg or "5" in msg.split(" ")[0]:
        return "server_error"
    if "permission" in msg or "denied" in msg:
        return "permission_denied"
    if "not found" in msg or "404" in msg:
        return "not_found"
    if "invalid" in msg or "validation" in msg:
        return "invalid_input"
    if "timeout" in msg:
        return "timeout"
    return "internal_error"


def _audit_tool_call(
    ctx: AgentToolContext,
    tool_name: str,
    input_kwargs: dict[str, Any],
    status: str,
    retry_count: int,
    output_summary: str,
    latency_ms: int | None = None,
) -> None:
    """Record a ToolCall row for audit and traceability."""
    trace_id = get_request_id()

    # Record Prometheus metrics
    from app.core.metrics import record_tool_call

    if latency_ms is not None:
        record_tool_call(tool_name, status, latency_ms)

    ctx.session.add(
        ToolCall(
            conversation_id=ctx.conversation_id,
            tool_name=tool_name,
            input_json=dump_json(_jsonable(input_kwargs)),
            output_summary=output_summary[:800],
            status=status,
            latency_ms=latency_ms or 0,
            trace_id=trace_id,
        )
    )
    ctx.session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# Schema helpers
# ══════════════════════════════════════════════════════════════════════════════


def _schema_from_signature(func: ToolFunction) -> dict[str, Any]:
    signature = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, parameter in signature.parameters.items():
        if param_name in {"ctx", "context"}:
            continue
        annotation = parameter.annotation
        properties[param_name] = {
            "type": _json_type(annotation),
            "description": param_name,
        }
        if parameter.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            properties[param_name]["default"] = parameter.default
    return {"type": "object", "properties": properties, "required": required}


def _json_type(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is list:
        return "array"
    if origin is Literal:
        return "string"
    args = [item for item in get_args(annotation) if item is not type(None)]
    if args:
        return _json_type(args[0])
    if annotation in {int, float}:
        return "number" if annotation is float else "integer"
    if annotation is bool:
        return "boolean"
    if annotation in {dict, Any}:
        return "object"
    return "string"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime | date):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _summarize_result(result: Any) -> str:
    value = _jsonable(result)
    if isinstance(value, dict):
        keys = ", ".join(list(value.keys())[:6])
        return f"dict({keys})"
    if isinstance(value, list):
        return f"list({len(value)})"
    return str(value)[:200]


# ══════════════════════════════════════════════════════════════════════════════
# Tool implementations
# ══════════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# search_games
# ---------------------------------------------------------------------------

@register_tool(
    name="search_games",
    description="搜索 Steam 游戏名称并返回候选 appid 列表。输入游戏名（中英文均可），返回按相关度排序的候选。",
    permissions="read",
    input_model=SearchGamesInput,
    output_description='{"query": "搜索词", "candidates": [{"appid": 730, "name": "Counter-Strike 2", "confidence": 0.95, ...}]}',
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR],
    timeout_s=12.0,
    retry_policy=RetryPolicy(max_retries=2, delay_s=0.5, retry_on=["timeout", "server_error"]),
)
async def search_games(ctx: AgentToolContext, query: str, limit: int = 5) -> dict[str, Any]:
    candidates = await ctx.steam.search_games(query)
    return {
        "query": query,
        "candidates": [item.model_dump(mode="json") for item in candidates[:limit]],
    }


# ---------------------------------------------------------------------------
# get_current_players
# ---------------------------------------------------------------------------

@register_tool(
    name="get_current_players",
    description="获取 Steam 游戏当前在线玩家数。实时 API 调用，结果可能缓存 5 分钟。",
    permissions="read",
    input_model=GetCurrentPlayersInput,
    output_description='{"appid": 730, "player_count": 1234567, "source_url": "...", "collected_at": "..."}',
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR, ToolErrorCode.RATE_LIMITED],
    timeout_s=12.0,
    retry_policy=RetryPolicy(max_retries=2, delay_s=1.0, retry_on=["timeout", "rate_limit", "server_error"]),
)
async def get_current_players(ctx: AgentToolContext, appid: int) -> dict[str, Any]:
    payload, source_url, collected_at = await ctx.steam.get_current_players(appid)
    response = payload.get("response", {}) if isinstance(payload, dict) else {}
    return {
        "appid": appid,
        "player_count": response.get("player_count"),
        "source_url": source_url,
        "collected_at": collected_at.isoformat(),
        "raw": payload,
    }


# ---------------------------------------------------------------------------
# get_appdetails
# ---------------------------------------------------------------------------

@register_tool(
    name="get_appdetails",
    description="获取 Steam Store 游戏详情：名称、价格、折扣、类型、开发商、发行商、推荐数等。支持指定地区和语言。",
    permissions="read",
    input_model=GetAppDetailsInput,
    output_description=(
        '{"appid": 730, "name": "Counter-Strike 2", '
        '"price": {"final_price": 0, "is_free": true}, "genres": [...]}'
    ),
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR, ToolErrorCode.NOT_FOUND],
    timeout_s=12.0,
    retry_policy=RetryPolicy(max_retries=2, delay_s=1.0, retry_on=["timeout", "server_error"]),
)
async def get_appdetails(
    ctx: AgentToolContext,
    appid: int,
    cc: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    data, source_url, collected_at = await ctx.steam.get_appdetails(appid, cc=cc, language=language)
    detail = ctx.steam.normalize_appdetails(
        appid,
        data,
        source_url=source_url,
        collected_at=collected_at,
        cc=cc,
        language=language,
    )
    return detail.model_dump(mode="json")


# ---------------------------------------------------------------------------
# get_game_news
# ---------------------------------------------------------------------------

@register_tool(
    name="get_game_news",
    description="获取 Steam 游戏最新新闻/公告。返回标题、URL 和摘要。",
    permissions="read",
    input_model=GetGameNewsInput,
    output_description='{"appid": 730, "news": [{"title": "...", "url": "...", "summary": "..."}], ...}',
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR],
    timeout_s=12.0,
)
async def get_game_news(ctx: AgentToolContext, appid: int, count: int = 5) -> dict[str, Any]:
    news, source_url, collected_at = await ctx.steam.get_game_news(appid, count=count)
    return {
        "appid": appid,
        "source_url": source_url,
        "collected_at": collected_at.isoformat(),
        "news": [item.model_dump(mode="json") for item in news],
    }


# ---------------------------------------------------------------------------
# get_achievement_stats
# ---------------------------------------------------------------------------

@register_tool(
    name="get_achievement_stats",
    description="获取 Steam 游戏全局成就完成率。可用于推断玩家进度分布和游戏难度。",
    permissions="read",
    input_model=GetAchievementStatsInput,
    output_description='{"appid": 730, "achievements": [{"name": "...", "percent": 45.2}, ...]}',
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR, ToolErrorCode.NOT_FOUND],
    timeout_s=12.0,
)
async def get_achievement_stats(ctx: AgentToolContext, appid: int, limit: int = 10) -> dict[str, Any]:
    data, source_url, collected_at = await ctx.steam.get_achievement_stats(appid)
    achievements = []
    if isinstance(data, dict):
        achievements = data.get("achievementpercentages", {}).get("achievements", [])
    return {
        "appid": appid,
        "source_url": source_url,
        "collected_at": collected_at.isoformat(),
        "achievements": achievements[: max(1, min(limit, 100))],
    }


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------

@register_tool(
    name="list_snapshots",
    description="查询本地数据库中指定游戏的历���快照记录。快照包含当时在线人数、价格、折扣等信息。",
    permissions="read",
    input_model=ListSnapshotsInput,
    output_description='{"appid": 730, "snapshots": [SnapshotRead, ...]}',
    timeout_s=5.0,
)
def list_snapshots_tool(ctx: AgentToolContext, appid: int, limit: int = 10) -> dict[str, Any]:
    snapshots = list_snapshots(ctx.session, appid=appid, limit=limit)
    return {
        "appid": appid,
        "snapshots": [snapshot.model_dump(mode="json") for snapshot in snapshots],
    }


# ---------------------------------------------------------------------------
# compare_snapshots
# ---------------------------------------------------------------------------

@register_tool(
    name="compare_snapshots",
    description="比较两个本地快照，输出逐字段对比结果（在线人数、价格、折扣等）及趋势解读。",
    permissions="read",
    input_model=CompareSnapshotsInput,
    output_description='{"left_snapshot_id": 1, "right_snapshot_id": 2, "metrics": [...], "summary": "..."}',
    error_codes=[ToolErrorCode.NOT_FOUND, ToolErrorCode.INVALID_INPUT],
    timeout_s=5.0,
)
def compare_snapshots_tool(
    ctx: AgentToolContext,
    left_snapshot_id: int,
    right_snapshot_id: int,
) -> dict[str, Any]:
    result = compare_snapshots(
        ctx.session,
        left=CompareTarget(snapshot_id=left_snapshot_id),
        right=CompareTarget(snapshot_id=right_snapshot_id),
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# save_snapshot  (write)
# ---------------------------------------------------------------------------

@register_tool(
    name="save_snapshot",
    description="采集当前 Steam 游戏数据并保存快照到本地数据库。写入操作，需用户确认。",
    permissions="write",
    input_model=SaveSnapshotInput,
    output_description="SnapshotRead — 新创建的快照对象",
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR, ToolErrorCode.RATE_LIMITED],
    timeout_s=18.0,
    retry_policy=RetryPolicy(max_retries=1, delay_s=2.0, retry_on=["timeout", "rate_limit"]),
)
async def save_snapshot(
    ctx: AgentToolContext,
    appid: int,
    cc: str | None = None,
    language: str | None = None,
) -> SnapshotRead:
    return await collect_snapshot(
        session=ctx.session,
        steam=ctx.steam,
        appid=appid,
        cc=cc,
        language=language,
        labels=[],
    )


# ---------------------------------------------------------------------------
# label_snapshot  (write)
# ---------------------------------------------------------------------------

@register_tool(
    name="label_snapshot",
    description="给本地快照打标签（如 '更新前'、'大促期间'），便于后续筛选和对比。",
    permissions="write",
    input_model=LabelSnapshotInput,
    output_description='{"snapshot_id": 5, "label": "更新前", "id": 1}',
    error_codes=[ToolErrorCode.NOT_FOUND, ToolErrorCode.INVALID_INPUT],
    timeout_s=3.0,
)
def label_snapshot(ctx: AgentToolContext, snapshot_id: int, label: str) -> dict[str, Any]:
    item = add_snapshot_label(ctx.session, snapshot_id=snapshot_id, label=label)
    return {"snapshot_id": item.snapshot_id, "label": item.label, "id": item.id}


# ---------------------------------------------------------------------------
# get_reviews
# ---------------------------------------------------------------------------

@register_tool(
    name="get_reviews",
    description="获取 Steam 用户评论原文。支持按语言过滤，返回评论内容、推荐/不推荐、游戏时长等信息。",
    permissions="read",
    input_model=GetReviewsInput,
    output_description='{"appid": 730, "reviews": [ReviewItem, ...], "source_url": "..."}',
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR, ToolErrorCode.RATE_LIMITED],
    timeout_s=18.0,
    retry_policy=RetryPolicy(max_retries=2, delay_s=1.0, retry_on=["timeout", "rate_limit", "server_error"]),
)
async def get_reviews(
    ctx: AgentToolContext,
    appid: int,
    count: int = 20,
    language: str = "schinese",
) -> dict[str, Any]:
    reviews, source_url, collected_at = await ReviewService().fetch_reviews(
        ctx.steam,
        appid=appid,
        language=language,
        count=count,
    )
    return {
        "appid": appid,
        "source_url": source_url,
        "collected_at": str(collected_at),
        "reviews": [review.model_dump(mode="json") for review in reviews],
    }


# ---------------------------------------------------------------------------
# analyze_reviews
# ---------------------------------------------------------------------------

@register_tool(
    name="analyze_reviews",
    description=(
        "分析 Steam 评论情绪、好评率和关键词，支持 LLM 话题提取。"
        "可指定样本量（建议≥100 以获得统计意义）、过滤正负评、时间窗口和语言分层。"
    ),
    permissions="read",
    input_model=AnalyzeReviewsInput,
    output_description="SentimentAnalysisResult — 包含好评率、关键词、话题摘要、分析时间",
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR, ToolErrorCode.RATE_LIMITED],
    timeout_s=30.0,
    retry_policy=RetryPolicy(max_retries=1, delay_s=2.0, retry_on=["timeout", "rate_limit"]),
)
async def analyze_reviews(
    ctx: AgentToolContext,
    appid: int,
    count: int = 100,
    review_type: str = "all",
    language: str = "schinese",
    days: int = 0,
) -> dict[str, Any]:
    import logging
    from datetime import UTC, datetime, timedelta

    log = logging.getLogger("steamanalysis.tools")

    service = ReviewService()
    reviews, source_url, _ = await service.fetch_reviews(
        ctx.steam,
        appid=appid,
        language=language,
        count=max(count, 100),  # fetch more to allow for filtering
    )

    # Apply review_type filter (positive / negative / all)
    if review_type == "positive":
        reviews = [r for r in reviews if r.voted_up]
    elif review_type == "negative":
        reviews = [r for r in reviews if not r.voted_up]

    # Apply time window filter
    if days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        reviews = [r for r in reviews if r.timestamp_created >= cutoff]
        log.info("Reviews filtered to last %d days: %d remaining", days, len(reviews))

    # Cap to requested count after filtering
    reviews = reviews[:count]

    # Use LLM-enhanced analysis when available, keyword fallback otherwise
    result = await service.analyze_sentiment_llm(
        appid=appid, reviews=reviews, source_url=source_url
    )
    service.save_analysis(ctx.session, result)
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# get_trend_analysis
# ---------------------------------------------------------------------------

@register_tool(
    name="get_trend_analysis",
    description="基于本地快照分析历史趋势：在线人数变化、价格波动、折扣规律等。",
    permissions="read",
    input_model=GetTrendAnalysisInput,
    output_description="TrendAnalysis — 包含趋势摘要、峰值/均值、价格变化列表、建议",
    timeout_s=5.0,
)
def get_trend_analysis(ctx: AgentToolContext, appid: int, days: int = 7) -> dict[str, Any]:
    analysis = analyze_snapshot_trend(ctx.session, appid=appid, days=days)
    return analysis.model_dump(mode="json")


# ---------------------------------------------------------------------------
# rag_search
# ---------------------------------------------------------------------------

@register_tool(
    name="rag_search",
    description="在本地知识库中执行关键词+向量混合检索（RRF 融合），支持按 appid 限定范围。",
    permissions="read",
    input_model=RagSearchInput,
    output_description="KnowledgeSearchResponse — 按相关度排序的文档片段列表",
    timeout_s=8.0,
)
def rag_search(
    ctx: AgentToolContext,
    query: str,
    appid: int | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    from app.schemas.knowledge import KnowledgeSearchRequest

    result = search_knowledge(
        ctx.session,
        KnowledgeSearchRequest(query=query, appid=appid, limit=limit),
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# analyze_web_sentiment
# ---------------------------------------------------------------------------

@register_tool(
    name="analyze_web_sentiment",
    description=(
        "搜索公开网页并分析游戏舆情、版本更新争议和玩家不满。"
        "自动抓取搜索结果并抽取观点，支持 LLM 和关键词双模式。"
        "⚠ 注意：此工具执行较慢（15-60 秒），会抓取多个网页。"
    ),
    permissions="read",
    input_model=AnalyzeWebSentimentInput,
    output_description="WebSentimentReport — 包含舆情摘要、情感倾向、证据来源、置信度",
    error_codes=[ToolErrorCode.TIMEOUT, ToolErrorCode.UPSTREAM_ERROR, ToolErrorCode.RATE_LIMITED],
    timeout_s=60.0,
    retry_policy=RetryPolicy(max_retries=0, delay_s=0.1, retry_on=[]),  # web sentiment is too expensive to retry
)
async def analyze_web_sentiment(
    ctx: AgentToolContext,
    query: str,
    game: str | None = None,
    appid: int | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    from app.schemas.web_sentiment import WebSentimentRequest

    result = await WebSentimentService().analyze(
        ctx.session,
        WebSentimentRequest(
            game=game,
            query=query,
            appid=appid,
            limit=limit,
            persist_to_knowledge=True,
        ),
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# recall_memory
# ---------------------------------------------------------------------------

@register_tool(
    name="recall_memory",
    description="搜索用户历史对话记忆，召回相关分析结论、偏好和讨论过的事实。用于跨会话上下文。",
    permissions="read",
    input_model=RecallMemoryInput,
    output_description='{"memories": [{"id": 1, "type": "fact", "content": "...", "importance": 0.8}], "count": 3}',
    timeout_s=5.0,
)
def recall_memory(
    ctx: AgentToolContext,
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Recall relevant memories from past conversations."""
    from app.services.memory_service import recall_memories

    if ctx.conversation_id is None:
        return {"memories": [], "count": 0}

    conversation = ctx.session.get(
        __import__("app.db.models", fromlist=["Conversation"]).Conversation,
        ctx.conversation_id,
    )
    user_id = conversation.user_id if conversation else None
    if user_id is None:
        return {"memories": [], "count": 0}

    memories = recall_memories(ctx.session, user_id, query, limit=limit)
    return {
        "memories": [
            {
                "id": m.id,
                "type": m.memory_type,
                "content": m.content,
                "importance": m.importance,
                "appid": m.appid,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ],
        "count": len(memories),
    }