"""Agent runtime with explicit state machine.

Refactored from TaskClassifier → scattered-handler pattern into a
deterministic state machine:

    PLAN → ACT → OBSERVE → SYNTHESIZE → VALIDATE → DONE

Each state has well-defined inputs, outputs, error handling, and produces
traceable steps.  The state machine is deterministic — the LLM Agent path
(SteamAnalysisAgent) handles open-ended reasoning when available.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlmodel import Session

from app.agent.memory import ConversationMemory
from app.agent.task_classifier import TaskClassification, TaskClassifier
from app.agent.tools import AgentToolContext, execute_tool
from app.agent.validators import validate_agent_result
from app.db.models import AgentCheckpoint, AgentRun, Conversation, Message, utc_now
from app.schemas.chat import (
    AgentAnalysisResult,
    AgentEvidence,
    AgentGameRef,
    AgentToolStep,
    ChatRequest,
    ClarificationOption,
)
from app.schemas.common import dump_json
from app.schemas.compare import CompareTarget
from app.schemas.snapshot import SnapshotRead
from app.services.comparison_service import compare_snapshots
from app.services.report_service import create_report
from app.services.snapshot_service import get_game_by_appid, list_snapshots
from app.services.steam_client import SteamClient

APPID_RE = re.compile(r"(?:appid\s*[:=]?\s*)?(\b\d{3,8}\b)", re.IGNORECASE)
CONTEXT_WORDS = ("它", "这个", "该游戏", "刚才", "上次", "之前")
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


# ══════════════════════════════════════════════════════════════════════════════
# State machine definition
# ══════════════════════════════════════════════════════════════════════════════


class AgentState(StrEnum):
    """States in the agent execution pipeline."""

    INIT = "init"               # entry — load conversation, set up trace
    PLAN = "plan"               # classify task, resolve context
    ACT = "act"                 # execute tools per plan
    OBSERVE = "observe"         # process and validate tool results
    SYNTHESIZE = "synthesize"   # build answer from observations
    VALIDATE = "validate"       # evidence check, risk check, freshness check
    DONE = "done"               # terminal — return result
    ERROR = "error"             # terminal — unrecoverable error


@dataclass
class AgentStateContext:
    """Immutable-ish context passed through state transitions.

    Each state reads from and writes to this context.  New context objects are
    created for state transitions to keep reasoning pure.
    """

    session: Session
    steam: SteamClient
    trace_id: str | None = None

    # Inputs (set during INIT)
    request: ChatRequest | None = None
    conversation: Conversation | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    recent_appids: list[int] = field(default_factory=list)

    # Outputs (built through the pipeline)
    trace: Any = None  # RuntimeTrace — set during INIT
    classification: TaskClassification | None = None
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    act_results: list[dict[str, Any]] = field(default_factory=list)
    result: AgentAnalysisResult | None = None
    report: Any = None  # AnalysisReport — set during DONE

    # Error
    error: str | None = None
    error_state: AgentState | None = None  # which state failed

    # Reflection loop support
    _reflection_count: int = 0
    _previous_issues: list[str] = field(default_factory=list)

    def current_state_label(self) -> str:
        """Human-readable label for the current state in progress displays."""
        if self.classification is None:
            return "INIT"
        return self.classification.task_type

    def add_trace_step(
        self,
        kind: str,
        summary: str,
        tool_name: str | None = None,
        status: str = "success",
        detail: dict[str, Any] | None = None,
    ) -> AgentToolStep:
        if self.trace is None:
            raise RuntimeError("trace not initialised")
        return self.trace.add(kind, summary, tool_name=tool_name, status=status, detail=detail)  # type: ignore[no-any-return]


# ══════════════════════════════════════════════════════════════════════════════
# RuntimeTrace (unchanged semantics, migrated here)
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class RuntimeTrace:
    steps: list[AgentToolStep] = field(default_factory=list)

    def add(
        self,
        kind: str,
        summary: str,
        tool_name: str | None = None,
        status: str = "success",
        detail: dict[str, Any] | None = None,
    ) -> AgentToolStep:
        step = AgentToolStep(
            kind=kind,  # type: ignore[arg-type]
            summary=summary,
            tool_name=tool_name,
            status=status,
            detail=detail or {},
        )
        self.steps.append(step)
        return step


# ══════════════════════════════════════════════════════════════════════════════
# State machine engine
# ══════════════════════════════════════════════════════════════════════════════


class AgentStateMachine:
    """Orchestrates the deterministic agent pipeline.

    Usage::

        machine = AgentStateMachine(session, steam, classifier)
        ctx = await machine.init(request, emit, trace_id)
        while ctx.result is None and ctx.error is None:
            ctx = await _STATE_TRANSITIONS[ctx.next_state](machine, ctx, emit)
        return ctx.conversation, ctx.report, ctx.result

    Supports self-reflection: when VALIDATE finds significant issues, the
    machine loops back to PLAN (up to MAX_REFLECTION_LOOPS times) to refine
    the analysis.
    """

    MAX_REFLECTION_LOOPS = 3
    REFLECTION_THRESHOLD = 2  # Minimum significant issues to trigger reflection

    _next_state_map: dict[AgentState, AgentState] = {
        AgentState.INIT: AgentState.PLAN,
        AgentState.PLAN: AgentState.ACT,
        AgentState.ACT: AgentState.OBSERVE,
        AgentState.OBSERVE: AgentState.SYNTHESIZE,
        AgentState.SYNTHESIZE: AgentState.VALIDATE,
        AgentState.VALIDATE: AgentState.DONE,
    }

    def __init__(
        self,
        session: Session,
        steam: SteamClient,
        classifier: TaskClassifier | None = None,
    ) -> None:
        self.session = session
        self.steam = steam
        self.classifier = classifier or TaskClassifier()
        self._latest_search_candidates: list[dict] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def handle(
        self,
        request: ChatRequest,
        emit: Emit | None = None,
        trace_id: str | None = None,
    ) -> tuple[Conversation, Any, AgentAnalysisResult]:
        """Run the full agent pipeline and return (conversation, report, result).

        Creates an ``AgentRun`` record for recoverability and writes an
        ``AgentCheckpoint`` at every state transition.  On failure the
        errored state is recorded as a failed checkpoint so execution
        traces remain inspectable.
        """
        # ── Create AgentRun ──────────────────────────────────────────
        run = AgentRun(
            conversation_id=None,  # will be set after INIT creates the conversation
            trace_id=trace_id,
            state="INIT",
            status="running",
            input_query=request.query,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        ctx = AgentStateContext(
            session=self.session,
            steam=self.steam,
            trace_id=trace_id,
            trace=RuntimeTrace(),
        )
        ctx._run_id = run.id  # type: ignore[attr-defined]

        # Transition loop
        current = AgentState.INIT
        while current not in (AgentState.DONE, AgentState.ERROR):
            next_state = self._next_state_map.get(current, AgentState.DONE)

            # Reflection: VALIDATE → PLAN when issues detected and loops remain
            if current == AgentState.VALIDATE and self._should_reflect(ctx):
                next_state = AgentState.PLAN
                ctx._reflection_count += 1
                ctx.add_trace_step(
                    "validate",
                    f"验证发现问题，启动反思循环 ({ctx._reflection_count}/{self.MAX_REFLECTION_LOOPS})。",
                    status="warning",
                    detail={
                        "loop": ctx._reflection_count,
                        "max": self.MAX_REFLECTION_LOOPS,
                        "issues": ctx._previous_issues[:5],
                    },
                )
                await self._emit(
                    emit,
                    "reflection",
                    {
                        "loop": ctx._reflection_count,
                        "max": self.MAX_REFLECTION_LOOPS,
                        "summary": "重新规划以解决验证问题。",
                        "trace_id": ctx.trace_id,
                    },
                )

            ctx = await self._transition(current, next_state, ctx, request, emit, run)
            current = next_state

        # ── Finalise AgentRun ────────────────────────────────────────
        run.state = current.value if hasattr(current, 'value') else str(current)
        if ctx.error:
            run.status = "failed"
            run.error_message = ctx.error[:2000]
        else:
            run.status = "completed"
            if ctx.result:
                run.output_answer = ctx.result.answer[:2000]
                run.result_json = dump_json(ctx.result.model_dump(mode="json"))
        if ctx.conversation:
            run.conversation_id = ctx.conversation.id
        run.completed_at = utc_now()
        self.session.add(run)
        self.session.commit()

        return ctx.conversation, ctx.report, ctx.result  # type: ignore[return-value]

    def _should_reflect(self, ctx: AgentStateContext) -> bool:
        """Determine if the agent should loop back to PLAN for re-analysis."""
        # Guard: max loops
        if ctx._reflection_count >= self.MAX_REFLECTION_LOOPS:
            return False

        # Guard: need a result to evaluate
        if ctx.result is None:
            return False

        # Check validation issues for significant problems
        validation_issues = ctx._previous_issues or []
        significant_issues = [
            issue
            for issue in validation_issues
            if any(
                keyword in issue.lower()
                for keyword in (
                    "missing", "empty", "not found", "insufficient",
                    "缺少", "不足", "未找到", "失败", "无法解析",
                    "无数据", "未获取", "不明确",
                )
            )
        ]

        # Only reflect if there are significant actionable issues
        if len(significant_issues) >= self.REFLECTION_THRESHOLD:
            # Clear the previous result to force re-synthesis
            ctx.result = None
            return True

        return False

    async def _transition(
        self,
        from_state: AgentState,
        to_state: AgentState,
        ctx: AgentStateContext,
        request: ChatRequest,
        emit: Emit | None,
        run: AgentRun | None = None,
    ) -> AgentStateContext:
        """Execute one state transition and return updated context.

        Writes an ``AgentCheckpoint`` row for the *from_state* so every
        state entry/exit is traceable.  A failed transition records an
        error checkpoint.
        """
        handler = getattr(self, f"_state_{from_state.value}", None)
        run_id = run.id if run else None
        started = utc_now()

        if handler is None:
            ctx.error = f"No handler for state {from_state.value}"
            ctx.error_state = from_state
            self._save_checkpoint(run_id, ctx.trace_id, from_state.value, "error",
                                  error_message=ctx.error)
            ctx = self._build_error_result(ctx)
            return ctx  # type: ignore[no-any-return]

        try:
            result_ctx = await handler(ctx, request, emit)
            # Record successful state → next_state transition checkpoint
            self._save_checkpoint(
                run_id, ctx.trace_id, from_state.value, "success",
                input_json=dump_json({"to_state": to_state.value}),
                output_json=dump_json({"result": "ok"}),
                started_at=started,
            )
            return result_ctx  # type: ignore[no-any-return]
        except Exception as exc:
            ctx.error = str(exc)
            ctx.error_state = from_state
            ctx.add_trace_step(
                to_state.value if hasattr(to_state, 'value') else "transition",
                f"状态 {from_state.value} → {to_state.value if hasattr(to_state, 'value') else 'next'} 出错: {exc}",
                status="error",
            )
            self._save_checkpoint(
                run_id, ctx.trace_id, from_state.value, "error",
                error_message=str(exc)[:2000],
                started_at=started,
            )
            return self._build_error_result(ctx)

    def _save_checkpoint(
        self,
        run_id: int | None,
        trace_id: str | None,
        state: str,
        status: str,
        *,
        input_json: str = "{}",
        output_json: str = "{}",
        error_message: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        """Persist an AgentCheckpoint row for observability."""
        if run_id is None:
            return
        checkpoint = AgentCheckpoint(
            run_id=run_id,
            trace_id=trace_id,
            state=state,
            input_json=input_json,
            output_json=output_json,
            status=status,
            error_message=error_message[:2000] if error_message else None,
            started_at=started_at or utc_now(),
            completed_at=utc_now(),
        )
        self.session.add(checkpoint)
        self.session.commit()

    # ------------------------------------------------------------------
    # INIT — load conversation, set up trace
    # ------------------------------------------------------------------

    async def _state_init(
        self,
        ctx: AgentStateContext,
        request: ChatRequest,
        emit: Emit | None,
    ) -> AgentStateContext:
        ctx.request = request
        ctx.conversation = self._ensure_conversation(request)
        memory = ConversationMemory(self.session)
        ctx.history = memory.load(ctx.conversation.id or 0)
        ctx.recent_appids = memory.recent_appids(ctx.history)

        self._record_message(ctx.conversation.id or 0, "user", request.query, trace_id=ctx.trace_id)

        await self._emit(emit, "thinking", {"summary": "正在加载对话上下文。", "trace_id": ctx.trace_id})
        ctx.add_trace_step("thinking", "已加载对话历史。", detail={"history_count": len(ctx.history)})
        return ctx

    # ------------------------------------------------------------------
    # PLAN — classify task, route to appropriate handler
    # ------------------------------------------------------------------

    async def _state_plan(
        self,
        ctx: AgentStateContext,
        request: ChatRequest,
        emit: Emit | None,
    ) -> AgentStateContext:
        assert request is not None

        # Inject reflection context if this is a reflection loop
        effective_query = request.query
        if ctx._reflection_count > 0 and ctx._previous_issues:
            issue_summary = "；".join(ctx._previous_issues[:3])
            effective_query = f"{request.query} [之前分析问题: {issue_summary}]"
            ctx.add_trace_step(
                "plan",
                f"反思循环 ({ctx._reflection_count}/{self.MAX_REFLECTION_LOOPS})，注入上下文。",
                detail={"reflection_count": ctx._reflection_count, "issues": ctx._previous_issues[:3]},
            )

        classification = await self.classifier.classify(effective_query, ctx.history)

        # Build plan steps based on task type
        ctx.plan_steps = self._build_plan(classification, effective_query)

        ctx.classification = classification
        task_clarification = self._build_task_clarification(request.query, classification)

        ctx.add_trace_step(
            "route",
            f"识别任务类型：{classification.task_type}",
            detail={
                "reason": classification.reason,
                "confidence": classification.confidence,
                "source": classification.source,
                "plan_steps": ctx.plan_steps,
            },
        )
        await self._emit(
            emit,
            "route",
            {
                "task_type": classification.task_type,
                "reason": classification.reason,
                "source": classification.source,
                "plan_steps": ctx.plan_steps,
                "trace_id": ctx.trace_id,
            },
        )

        # Store task clarification for later injection
        ctx._task_clarification = task_clarification  # type: ignore[attr-defined]
        return ctx

    # ------------------------------------------------------------------
    # ACT — execute tools based on plan
    # ------------------------------------------------------------------

    async def _state_act(
        self,
        ctx: AgentStateContext,
        _request: ChatRequest,
        emit: Emit | None,
    ) -> AgentStateContext:
        assert ctx.classification is not None

        tool_ctx = AgentToolContext(
            session=self.session,
            steam=self.steam,
            conversation_id=ctx.conversation.id if ctx.conversation else None,
        )

        task = ctx.classification.task_type
        query = ctx.request.query if ctx.request else ""
        auto_collect = ctx.request.auto_collect if ctx.request else False
        confirmed_write = ctx.request.confirmed_write if ctx.request else False

        if task == "game_comparison":
            ctx.act_results = await self._act_comparison(
                tool_ctx, query, ctx, emit, auto_collect, confirmed_write,
            )
        elif task == "review_analysis":
            ctx.act_results = await self._act_review(tool_ctx, query, ctx, emit)
        elif task == "history_trend":
            ctx.act_results = await self._act_trend(tool_ctx, query, ctx, emit)
        elif task == "market_intelligence":
            ctx.act_results = await self._act_market(tool_ctx, query, ctx, emit)
        elif task == "web_sentiment":
            ctx.act_results = await self._act_web_sentiment(tool_ctx, query, ctx, emit)
        elif task in ("export", "schedule_monitor"):
            ctx.act_results = [{"kind": "confirmation", "task_type": task}]
        else:
            # single_game or unknown
            ctx.act_results = await self._act_single_game(
                tool_ctx, query, ctx, emit, auto_collect, confirmed_write,
            )

        await self._emit(emit, "observation", {
            "summary": f"工具执行完成，共 {len(ctx.act_results)} 个结果。",
            "trace_id": ctx.trace_id,
        })
        return ctx

    # ------------------------------------------------------------------
    # OBSERVE — process and validate tool results
    # ------------------------------------------------------------------

    async def _state_observe(
        self,
        ctx: AgentStateContext,
        _request: ChatRequest,
        emit: Emit | None,
    ) -> AgentStateContext:
        """Validate act_results and surface uncertainties."""
        uncertainties: list[str] = []

        for item in ctx.act_results:
            if item.get("kind") == "error":
                uncertainties.append(f"工具 {item.get('tool', 'unknown')} 执行失败: {item.get('error')}")
            elif item.get("kind") == "confirmation":
                # Already handled in SYNTHESIZE — no observation needed
                pass
            elif item.get("kind") == "empty":
                uncertainties.append(item.get("message", "未获取到有效数据"))

        if not ctx.act_results:
            uncertainties.append("没有工具执行结果。")

        # Store observations on context
        ctx._observations_uncertainties = uncertainties  # type: ignore[attr-defined]
        ctx._observations_appids = self._extract_appids_from_results(ctx.act_results)  # type: ignore[attr-defined]

        await self._emit(emit, "thinking", {
            "summary": f"观察结果: {len(ctx.act_results)} 个工具调用, {len(uncertainties)} 个不确定项。",
            "trace_id": ctx.trace_id,
        })
        return ctx

    # ------------------------------------------------------------------
    # SYNTHESIZE — build answer from observations
    # ------------------------------------------------------------------

    async def _state_synthesize(
        self,
        ctx: AgentStateContext,
        _request: ChatRequest,
        emit: Emit | None,
    ) -> AgentStateContext:
        """Assemble the final AgentAnalysisResult from act_results."""
        assert ctx.classification is not None

        result = self._synthesize_result(ctx)

        # Inject task-level clarification candidates if applicable
        task_clarification = getattr(ctx, '_task_clarification', [])
        if not result.candidates and task_clarification and not result.requires_human_confirmation:
            result.candidates = task_clarification

        # Attach all trace steps
        result.agent_steps = ctx.trace.steps if ctx.trace else []
        result.memory_used = bool(ctx.history)
        result.classification_reason = ctx.classification.reason

        # Run validators (preliminary — VALIDATE state does deeper checks)
        uncertainties = getattr(ctx, '_observations_uncertainties', [])
        result.uncertainties = [
            *result.uncertainties,
            *uncertainties,
        ]

        ctx.result = result
        await self._emit(emit, "thinking", {
            "summary": "正在整合分析结果。",
            "trace_id": ctx.trace_id,
        })
        return ctx

    # ------------------------------------------------------------------
    # VALIDATE — evidence, risk, freshness, source checks
    # ------------------------------------------------------------------

    async def _state_validate(
        self,
        ctx: AgentStateContext,
        _request: ChatRequest,
        emit: Emit | None,
    ) -> AgentStateContext:
        """Run validators and add warnings."""
        assert ctx.result is not None

        validation_issues = validate_agent_result(ctx.result)
        # Save issues for potential reflection loop
        ctx._previous_issues = validation_issues
        if validation_issues:
            ctx.result.uncertainties = [*ctx.result.uncertainties, *validation_issues]
            ctx.add_trace_step(
                "observation",
                f"验证发现 {len(validation_issues)} 个问题。",
                status="warning" if len(validation_issues) > 0 else "success",
                detail={"issues": validation_issues},
            )
            await self._emit(emit, "validation", {
                "issues": validation_issues,
                "trace_id": ctx.trace_id,
            })

        # Create report if there's an answer
        if ctx.result.answer:
            ctx.report = create_report(
                self.session,
                query=ctx.request.query if ctx.request else "",
                answer_markdown=ctx.result.answer,
                structured_result={"result": ctx.result.model_dump(mode="json")},
                evidence=[item.model_dump(mode="json") for item in ctx.result.evidence],
                snapshot_ids=[
                    step.detail["snapshot_id"]
                    for step in (ctx.trace.steps if ctx.trace else [])
                    if "snapshot_id" in step.detail
                ],
                trace_id=ctx.trace_id,
            )

        # Record assistant message
        if ctx.conversation:
            self._record_message(
                ctx.conversation.id or 0,
                "assistant",
                ctx.result.answer,
                {"result": ctx.result.model_dump(mode="json")},
                trace_id=ctx.trace_id,
            )

        return ctx

    # ------------------------------------------------------------------
    # Plan builder
    # ------------------------------------------------------------------

    def _build_plan(self, classification: TaskClassification, query: str) -> list[dict[str, Any]]:
        task = classification.task_type
        plan: list[dict] = []

        if task in ("single_game", "unknown"):
            plan = [
                {"step": 1, "action": "resolve_appids", "desc": "解析游戏名 → appid"},
                {"step": 2, "action": "get_current_players", "desc": "查询当前在线人数"},
                {"step": 3, "action": "get_appdetails", "desc": "查询基础信息和价格"},
                {"step": 4, "action": "get_game_news", "desc": "查询最近新闻"},
            ]
        elif task == "game_comparison":
            plan = [
                {"step": 1, "action": "resolve_appids", "desc": "解析多个游戏名", "desired": 2},
                {"step": 2, "action": "save_snapshot_or_load", "desc": "采集或加载快照"},
                {"step": 3, "action": "compare_snapshots", "desc": "逐指标对比"},
            ]
        elif task == "review_analysis":
            plan = [
                {"step": 1, "action": "resolve_appids", "desc": "解析游戏名"},
                {"step": 2, "action": "analyze_reviews", "desc": "分析评论情绪和关键词"},
            ]
        elif task == "history_trend":
            plan = [
                {"step": 1, "action": "resolve_appids", "desc": "解析游戏名"},
                {"step": 2, "action": "get_trend_analysis", "desc": "分析历史快照趋势"},
            ]
        elif task == "market_intelligence":
            plan = [
                {"step": 1, "action": "resolve_appids", "desc": "解析多个游戏名", "desired": 3},
                {"step": 2, "action": "get_appdetails", "desc": "逐个获取详情"},
                {"step": 3, "action": "get_current_players", "desc": "逐个获取在线人数"},
            ]
        elif task == "web_sentiment":
            plan = [
                {"step": 1, "action": "analyze_web_sentiment", "desc": "搜索并分析网页舆情"},
            ]

        return plan

    # ------------------------------------------------------------------
    # ACT helpers — each returns list[dict] of act_results
    # ------------------------------------------------------------------

    async def _act_single_game(
        self,
        tool_ctx: AgentToolContext,
        query: str,
        ctx: AgentStateContext,
        emit: Emit | None,
        auto_collect: bool,
        confirmed_write: bool,
    ) -> list[dict[str, Any]]:
        appids, assumptions, uncertainties = await self._resolve_appids(
            tool_ctx, query, ctx, emit, ctx.recent_appids,
        )
        if not appids:
            return [{
                "kind": "empty",
                "message": "未找到明确 appid",
                "assumptions": assumptions,
                "uncertainties": [*uncertainties, "游戏名解析不确定"],
            }]

        appid = appids[0]
        results = [{
            "kind": "appid_resolved", "appid": appid,
            "assumptions": assumptions, "uncertainties": uncertainties,
        }]

        if auto_collect and not confirmed_write:
            return results + [{"kind": "confirmation", "task_type": "single_game", "appid": appid, "risk_level": "L2"}]

        if auto_collect and confirmed_write:
            snapshot = await self._run_tool(tool_ctx, "save_snapshot", ctx, emit, appid=appid)
            ctx.trace.steps[-1].detail["snapshot_id"] = snapshot.id if hasattr(snapshot, 'id') else 0
            game = get_game_by_appid(self.session, appid)
            return results + [{
                "kind": "snapshot_saved", "snapshot": snapshot,
                "game_name": game.name if game else None,
            }]

        players = await self._run_tool(tool_ctx, "get_current_players", ctx, emit, appid=appid)
        details = await self._run_tool(tool_ctx, "get_appdetails", ctx, emit, appid=appid)
        await self._run_tool(tool_ctx, "get_game_news", ctx, emit, appid=appid, count=3)
        return results + [
            {"kind": "players", "data": players},
            {"kind": "details", "data": details},
        ]

    async def _act_comparison(
        self,
        tool_ctx: AgentToolContext,
        query: str,
        ctx: AgentStateContext,
        emit: Emit | None,
        auto_collect: bool,
        confirmed_write: bool,
    ) -> list[dict[str, Any]]:
        appids, assumptions, uncertainties = await self._resolve_appids(
            tool_ctx, query, ctx, emit, ctx.recent_appids, desired=2,
        )
        if not appids:
            return [{"kind": "empty", "message": "解析不到两个游戏的 appid", "uncertainties": uncertainties}]

        results: list[dict] = [{"kind": "appids_resolved", "appids": appids[:2], "assumptions": assumptions}]
        snapshots: list[SnapshotRead] = []

        for appid in appids[:2]:
            if auto_collect and not confirmed_write:
                return results + [{
                    "kind": "confirmation", "task_type": "game_comparison",
                    "risk_level": "L2", "appids": appids[:2],
                }]
            if auto_collect and confirmed_write:
                snapshot = await self._run_tool(tool_ctx, "save_snapshot", ctx, emit, appid=appid)
                ctx.trace.steps[-1].detail["snapshot_id"] = snapshot.id if hasattr(snapshot, 'id') else 0
                snapshots.append(snapshot)
            else:
                saved = list_snapshots(self.session, appid=appid, limit=1)
                snapshots.extend(saved)

        results.append({"kind": "snapshots", "data": snapshots})

        if len(snapshots) >= 2:
            comparison = compare_snapshots(
                self.session,
                left=CompareTarget(snapshot_id=snapshots[0].id),
                right=CompareTarget(snapshot_id=snapshots[1].id),
            )
            ctx.add_trace_step("observation", "已完成确定性数值对比。", tool_name="compare_snapshots")
            results.append({"kind": "comparison", "data": comparison})
        else:
            results.append({"kind": "empty", "message": "可比较快照不足，需要至少两个快照。"})

        return results

    async def _act_review(
        self,
        tool_ctx: AgentToolContext,
        query: str,
        ctx: AgentStateContext,
        emit: Emit | None,
    ) -> list[dict[str, Any]]:
        appids, assumptions, uncertainties = await self._resolve_appids(
            tool_ctx, query, ctx, emit, ctx.recent_appids,
        )
        if not appids:
            return [{"kind": "empty", "message": "解析不到游戏 appid", "uncertainties": uncertainties}]
        appid = appids[0]
        analysis = await self._run_tool(tool_ctx, "analyze_reviews", ctx, emit, appid=appid, count=100)
        return [
            {"kind": "appid_resolved", "appid": appid, "assumptions": assumptions},
            {"kind": "review_analysis", "data": analysis},
        ]

    async def _act_trend(
        self,
        tool_ctx: AgentToolContext,
        query: str,
        ctx: AgentStateContext,
        emit: Emit | None,
    ) -> list[dict[str, Any]]:
        appids, assumptions, uncertainties = await self._resolve_appids(
            tool_ctx, query, ctx, emit, ctx.recent_appids,
        )
        if not appids:
            return [{"kind": "empty", "message": "解析不到游戏 appid"}]
        appid = appids[0]
        trend = await self._run_tool(tool_ctx, "get_trend_analysis", ctx, emit, appid=appid, days=7)
        return [
            {"kind": "appid_resolved", "appid": appid, "assumptions": assumptions},
            {"kind": "trend_analysis", "data": trend},
        ]

    async def _act_market(
        self,
        tool_ctx: AgentToolContext,
        query: str,
        ctx: AgentStateContext,
        emit: Emit | None,
    ) -> list[dict[str, Any]]:
        appids, assumptions, uncertainties = await self._resolve_appids(
            tool_ctx, query, ctx, emit, ctx.recent_appids, desired=3,
        )
        if not appids:
            return [{"kind": "empty", "message": "解析不到候选游戏"}]
        results: list[dict] = [{"kind": "appids_resolved", "appids": appids[:3], "assumptions": assumptions}]
        for appid in appids[:3]:
            details = await self._run_tool(tool_ctx, "get_appdetails", ctx, emit, appid=appid)
            players = await self._run_tool(tool_ctx, "get_current_players", ctx, emit, appid=appid)
            results.append({"kind": "market_entry", "appid": appid, "details": details, "players": players})
        return results

    async def _act_web_sentiment(
        self,
        tool_ctx: AgentToolContext,
        query: str,
        ctx: AgentStateContext,
        emit: Emit | None,
    ) -> list[dict[str, Any]]:
        analysis = await self._run_tool(tool_ctx, "analyze_web_sentiment", ctx, emit, query=query, limit=5)
        return [{"kind": "web_sentiment", "data": analysis}]

    # ------------------------------------------------------------------
    # SYNTHESIZE — build result from act_results
    # ------------------------------------------------------------------

    def _synthesize_result(self, ctx: AgentStateContext) -> AgentAnalysisResult:
        assert ctx.classification is not None

        task = ctx.classification.task_type
        results = ctx.act_results

        # Check for confirmation-required (from act_results)
        for item in results:
            if item.get("kind") == "confirmation":
                return self._build_confirmation_result(ctx, item)

        # Check for empty results
        empty_items = [item for item in results if item.get("kind") == "empty"]
        if empty_items and not any(item.get("kind") not in ("empty", "appid_resolved", "appids_resolved") for item in results):
            return self._build_empty_result(ctx, empty_items)

        if task == "game_comparison":
            return self._synthesize_comparison(ctx, results)
        elif task == "review_analysis":
            return self._synthesize_review(ctx, results)
        elif task == "history_trend":
            return self._synthesize_trend(ctx, results)
        elif task == "market_intelligence":
            return self._synthesize_market(ctx, results)
        elif task == "web_sentiment":
            return self._synthesize_web_sentiment(ctx, results)
        elif task in ("export", "schedule_monitor"):
            return self._synthesize_confirmation(ctx, task)
        else:
            return self._synthesize_single_game(ctx, results)

    def _build_confirmation_result(self, ctx: AgentStateContext, item: dict) -> AgentAnalysisResult:
        assert ctx.classification is not None
        task_type = item.get("task_type", ctx.classification.task_type)
        risk = item.get("risk_level", "L2")
        appids = item.get("appids") or [item.get("appid")] if item.get("appid") else []
        games = [AgentGameRef(appid=a, name=self._game_name(a)) for a in appids]

        if task_type == "game_comparison":
            answer = f"将为 {len(appids)} 个游戏采集快照并进行对比。\n\n快照采集是写入操作（L2 风险等级），请确认后执行。"
        else:
            game_name = self._game_name(appids[0]) if appids else "unknown"
            answer = f"将为 {game_name} 采集快照并保存到本地数据库。\n\n这是写入操作（L2 风险等级），请确认后执行。"

        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level=risk,  # type: ignore[call-arg]  # type: ignore[arg-type]
            answer=answer,
            games=games,
            requires_human_confirmation=True,
        )

    def _build_empty_result(self, ctx: AgentStateContext, empty_items: list[dict]) -> AgentAnalysisResult:
        assert ctx.classification is not None
        uncertainties: list[str] = []
        for item in empty_items:
            uncertainties.extend(item.get("uncertainties", []))
        answer = "我没有找到足够明确的信息。请提供更具体的游戏名或 appid。"
        candidates = self._build_clarification_candidates(uncertainties)
        if candidates:
            answer += " 以下可能是你要找的游戏："
        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level="L1",
            answer=answer,
            uncertainties=[*uncertainties, "游戏名解析不确定。"],
            candidates=candidates,
        )

    def _build_confirmation_result2(self, ctx: AgentStateContext, answer: str, risk: str = "L3") -> AgentAnalysisResult:
        assert ctx.classification is not None
        ctx.add_trace_step("thinking", "该任务需要用户确认后再执行。")
        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level=risk,  # type: ignore[arg-type]
            answer=answer,
            uncertainties=["当前对话不会直接执行需要确认的写入/导出操作。"],
            requires_human_confirmation=True,
        )

    def _synthesize_single_game(self, ctx: AgentStateContext, results: list[dict]) -> AgentAnalysisResult:
        assert ctx.classification is not None

        # Check for snapshot_saved
        for item in results:
            if item.get("kind") == "snapshot_saved":
                snapshot = item["snapshot"]
                game_name = item.get("game_name")
                return AgentAnalysisResult(
                    task_type=ctx.classification.task_type,
                    risk_level="L2",
                    answer=self._snapshot_answer(snapshot, game_name),
                    games=[AgentGameRef(appid=snapshot.appid, name=game_name)],
                    evidence=self._snapshot_evidence(snapshot),
                    recommended_next_steps=["可以继续问「和上次比怎么样」，或给当前快照打标签。"],
                )

        players_data = {}
        details_data = {}
        appid = 0
        assumptions: list[str] = []
        uncertainties: list[str] = []

        for item in results:
            if item.get("kind") == "appid_resolved":
                appid = item["appid"]
                assumptions = item.get("assumptions", [])
                uncertainties = item.get("uncertainties", [])
            elif item.get("kind") == "players":
                players_data = item["data"]
            elif item.get("kind") == "details":
                details_data = item["data"]

        name = details_data.get("name") or f"appid {appid}"
        player_count = players_data.get("player_count")
        price = details_data.get("price") or {}
        player_text = f"{player_count:,}" if isinstance(player_count, int) else "暂无可用数值"

        answer = (
            f"## {name}\n\n"
            f"当前在线人数：{player_text}。\n\n"
            f"价格/折扣：{self._price_sentence(price)}\n\n"
            "本次为只读查询，未保存本地快照。"
        )

        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level="L1",
            answer=answer,
            games=[AgentGameRef(appid=appid, name=name)],
            evidence=[
                AgentEvidence(
                    source="Steam GetNumberOfCurrentPlayers",
                    url=players_data.get("source_url"),
                    collected_at=self._parse_datetime(players_data.get("collected_at")),
                    summary="当前在线人数",
                ),
                AgentEvidence(
                    source="Steam Store appdetails",
                    url=details_data.get("source_url"),
                    collected_at=self._parse_datetime(details_data.get("collected_at")),
                    summary="基础信息、价格与折扣",
                ),
            ],
            assumptions=assumptions,
            uncertainties=uncertainties,
            recommended_next_steps=["打开自动采集后可保存快照，用于后续趋势分析。"],
        )

    def _synthesize_comparison(self, ctx: AgentStateContext, results: list[dict]) -> AgentAnalysisResult:
        assert ctx.classification is not None
        comparison = None
        snapshots: list[SnapshotRead] = []
        assumptions: list[str] = []
        uncertainties: list[str] = []

        for item in results:
            if item.get("kind") == "comparison":
                comparison = item["data"]
            elif item.get("kind") == "snapshots":
                snapshots = item["data"]
            elif item.get("kind") == "appids_resolved":
                assumptions = item.get("assumptions", [])

        if comparison is None:
            return AgentAnalysisResult(
                task_type=ctx.classification.task_type,
                risk_level="L1",
                answer="对比需要两个可用快照。请提供两个游戏/appid，或先为目标游戏采集至少两个快照。",
                assumptions=assumptions,
                uncertainties=[*uncertainties, "可比较快照数量不足。"],
            )

        answer = (
            "## 对比结论\n\n"
            f"{comparison.summary}\n\n"
            f"- 左侧快照：`{comparison.left_snapshot_id}`，appid `{comparison.left_appid}`\n"
            f"- 右侧快照：`{comparison.right_snapshot_id}`，appid `{comparison.right_appid}`\n"
            f"- 地区可比：`{comparison.comparable_region}`；币种可比：`{comparison.comparable_currency}`\n\n"
            "### 深度解读\n\n"
            f"{self._comparison_interpretation(comparison.model_dump(mode='json'))}"
        )

        evidence = []
        for snapshot in snapshots[:2]:
            evidence.extend(self._snapshot_evidence(snapshot))

        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level="L2",
            answer=answer,
            games=[AgentGameRef(appid=item.appid, name=self._game_name(item.appid)) for item in snapshots[:2]],
            evidence=evidence,
            assumptions=assumptions,
            uncertainties=[*uncertainties, *comparison.uncertainties],
            recommended_next_steps=["可以继续请求「分析最近 7 天趋势」，或增加更多时间点快照。"],
        )

    def _synthesize_review(self, ctx: AgentStateContext, results: list[dict]) -> AgentAnalysisResult:
        assert ctx.classification is not None
        appid = 0
        assumptions: list[str] = []
        analysis_data = {}
        for item in results:
            if item.get("kind") == "appid_resolved":
                appid = item["appid"]
                assumptions = item.get("assumptions", [])
            elif item.get("kind") == "review_analysis":
                analysis_data = item["data"]

        if not analysis_data:
            return AgentAnalysisResult(
                task_type=ctx.classification.task_type,
                risk_level="L1",
                answer="评论分析未返回有效数据。",
                assumptions=assumptions,
            )

        game_name = self._game_name(appid)
        answer = (
            f"## {game_name or f'appid {appid}'} 评论分析\n\n"
            f"- 样本数：{analysis_data['total_reviews']}\n"
            f"- 样本好评率：{analysis_data['positive_ratio']:.0%}\n"
            f"- 玩家主要夸：{self._join_or_empty(analysis_data['top_praise_keywords'])}\n"
            f"- 玩家主要吐槽：{self._join_or_empty(analysis_data['top_complaint_keywords'])}\n\n"
            f"{analysis_data['summary']}\n\n"
            "提示：这是最近评论抽样分析，不等同于 Steam 总体评价。"
        )

        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level="L1",
            answer=answer,
            games=[AgentGameRef(appid=appid, name=game_name)],
            evidence=[
                AgentEvidence(
                    source="Steam Store appreviews",
                    url=analysis_data.get("source_url"),
                    collected_at=self._parse_datetime(analysis_data.get("analyzed_at")),
                    summary="最近用户评论抽样",
                )
            ],
            assumptions=assumptions,
            recommended_next_steps=["可以指定「只看差评」或提高样本量继续分析。"],
        )

    def _synthesize_trend(self, ctx: AgentStateContext, results: list[dict]) -> AgentAnalysisResult:
        assert ctx.classification is not None
        appid = 0
        assumptions: list[str] = []
        trend_data = {}
        for item in results:
            if item.get("kind") == "appid_resolved":
                appid = item["appid"]
                assumptions = item.get("assumptions", [])
            elif item.get("kind") == "trend_analysis":
                trend_data = item["data"]

        if not trend_data:
            return AgentAnalysisResult(
                task_type=ctx.classification.task_type,
                risk_level="L1",
                answer="趋势分析未返回有效数据。",
                assumptions=assumptions,
            )

        evidence: list[AgentEvidence] = []
        snapshots = trend_data.get("snapshots", [])
        for item in snapshots[-2:]:
            source_urls = item.get("source_urls") or {}
            evidence.append(AgentEvidence(
                source=f"Local game_snapshot {item.get('id')}",
                url=source_urls.get("current_players") or source_urls.get("store_appdetails"),
                collected_at=self._parse_datetime(item.get("collected_at")),
                summary=f"appid {appid} 历史快照",
            ))

        answer = (
            f"## {self._game_name(appid) or f'appid {appid}'} 趋势分析\n\n"
            f"{trend_data['summary']}\n\n"
            f"- 快照数量：{trend_data['snapshot_count']}\n"
            f"- 在线峰值：{trend_data['player_count_peak'] or '暂无'}\n"
            f"- 在线均值：{trend_data['player_count_avg'] or '暂无'}\n"
            f"- 价格变化次数：{len(trend_data['price_changes'])}\n\n"
            f"建议：{trend_data['recommendation']}"
        )

        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level="L1",
            answer=answer,
            games=[AgentGameRef(appid=appid, name=self._game_name(appid))],
            evidence=evidence,
            assumptions=assumptions,
            uncertainties=[] if evidence else ["本地历史快照不足，趋势结论有限。"],
            recommended_next_steps=["可以开启定时采集，让趋势判断更稳定。"],
        )

    def _synthesize_market(self, ctx: AgentStateContext, results: list[dict]) -> AgentAnalysisResult:
        assert ctx.classification is not None
        assumptions: list[str] = []

        lines = ["## 市场洞察\n"]
        evidence: list[AgentEvidence] = []
        games: list[AgentGameRef] = []

        for item in results:
            if item.get("kind") == "appids_resolved":
                assumptions = item.get("assumptions", [])
            elif item.get("kind") == "market_entry":
                appid = item["appid"]
                details = item["details"]
                players = item["players"]
                name = details.get("name") or f"appid {appid}"
                games.append(AgentGameRef(appid=appid, name=name))
                lines.append(
                    f"- **{name}**：当前在线 {players.get('player_count') or '暂无'}，"
                    f"{self._price_sentence(details.get('price') or {})}"
                )
                evidence.append(AgentEvidence(
                    source="Steam Store appdetails",
                    url=details.get("source_url"),
                    collected_at=self._parse_datetime(details.get("collected_at")),
                    summary=f"{name} 价格与基础信息",
                ))
                evidence.append(AgentEvidence(
                    source="Steam GetNumberOfCurrentPlayers",
                    url=players.get("source_url"),
                    collected_at=self._parse_datetime(players.get("collected_at")),
                    summary=f"{name} 当前在线人数",
                ))

        lines.append("\n当前市场洞察为候选游戏的快速扫描；更完整的推荐需要明确关注列表或更多历史快照。")

        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level="L1",
            answer="\n".join(lines),
            games=games,
            evidence=evidence,
            assumptions=assumptions,
            recommended_next_steps=["提供关注列表后，可以做更稳定的多游戏排序。"],
        )

    def _synthesize_web_sentiment(self, ctx: AgentStateContext, results: list[dict]) -> AgentAnalysisResult:
        assert ctx.classification is not None
        ws_data = {}
        for item in results:
            if item.get("kind") == "web_sentiment":
                ws_data = item["data"]

        if not ws_data:
            return AgentAnalysisResult(
                task_type=ctx.classification.task_type,
                risk_level="L1",
                answer="网页舆情分析未返回有效数据。",
            )

        uncertainties = ws_data.get("uncertainties", [])
        answer = (
            f"## 网页舆情分析：{ws_data.get('game_key', '未知')}\n\n"
            f"{ws_data.get('summary', '')}\n\n"
            f"- 情感倾向：{ws_data.get('sentiment', 'unknown')}\n"
            f"- 风险强度：{ws_data.get('severity', 'low')}\n"
            f"- 置信度：{ws_data.get('confidence', 0):.0%}\n"
            f"- 来源数：{len(ws_data.get('sources', []))} 个网页\n"
            f"- 观点数：{len(ws_data.get('claims', []))} 条\n\n"
            f"不确定项：{'；'.join(uncertainties) if uncertainties else '无'}"
        )

        evidence: list[AgentEvidence] = []
        for src in ws_data.get("sources", [])[:5]:
            evidence.append(AgentEvidence(
                source=src.get("source_type", "web"),
                url=src.get("source_url"),
                collected_at=self._parse_datetime(src.get("fetched_at")),
                summary=f"{src.get('title', '')}: {src.get('excerpt', '')[:100]}",
            ))

        return AgentAnalysisResult(
            task_type=ctx.classification.task_type,
            risk_level="L1",
            answer=answer,
            evidence=evidence,
            uncertainties=uncertainties,
            recommended_next_steps=ws_data.get("recommended_next_steps", []),
        )

    def _synthesize_confirmation(self, ctx: AgentStateContext, task: str) -> AgentAnalysisResult:
        assert ctx.classification is not None
        if task == "export":
            return self._build_confirmation_result2(
                ctx,
                "导出报告属于 L3 操作，需要你明确选择报告和格式后再执行。可使用报告列表里的导出入口。",
            )
        return self._build_confirmation_result2(
            ctx,
            "定时监控会写入本地任务配置，属于 L2 操作。请在设置/监控面板里确认 appid、间隔和启用状态后创建。",
            risk="L2",
        )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _build_error_result(self, ctx: AgentStateContext) -> AgentStateContext:
        ctx.result = AgentAnalysisResult(
            task_type=ctx.classification.task_type if ctx.classification else "unknown",
            risk_level="L1",
            answer=f"处理出错：{ctx.error}。请重试或提供更详细的信息。",
            agent_steps=ctx.trace.steps if ctx.trace else [],
            uncertainties=[f"Agent 状态 '{ctx.error_state.value if ctx.error_state else 'unknown'}' 处理失败。"],
        )
        return ctx

    # ------------------------------------------------------------------
    # Shared helpers (preserved from original runtime.py)
    # ------------------------------------------------------------------

    async def _resolve_appids(
        self,
        ctx: AgentToolContext,
        query: str,
        state_ctx: AgentStateContext,
        emit: Emit | None,
        recent_appids: list[int],
        desired: int = 1,
    ) -> tuple[list[int], list[str], list[str]]:
        explicit = [int(match.group(1)) for match in APPID_RE.finditer(query)]
        if explicit:
            return list(dict.fromkeys(explicit))[:desired], [], []

        if recent_appids and any(word in query for word in CONTEXT_WORDS):
            return recent_appids[:desired], ["根据对话历史沿用上一款游戏。"], []

        targets = self._split_targets(query, desired)
        appids: list[int] = []
        assumptions: list[str] = []
        uncertainties: list[str] = []
        for target in targets:
            search = await self._run_tool(ctx, "search_games", state_ctx, emit, query=target, limit=3)
            candidates = search.get("candidates") or []
            if not candidates:
                uncertainties.append(f"未搜索到「{target}」的 Steam 候选。")
                continue
            top = candidates[0]
            appids.append(int(top["appid"]))
            assumptions.append(f"按 Steam 搜索结果，将「{target}」解析为 {top['name']} (appid {top['appid']})。")
            if len(candidates) > 1 and float(top.get("confidence") or 0) < 0.75:
                uncertainties.append(f"「{target}」存在多个候选，当前选用了第一个结果。")
        return list(dict.fromkeys(appids))[:desired], assumptions, uncertainties

    def _split_targets(self, query: str, desired: int) -> list[str]:
        cleaned = query.strip()
        for token in ("对比一下", "比较一下", "对比", "比较", "评论", "评价", "趋势", "历史", "市场", "推荐"):
            cleaned = cleaned.replace(token, " ")
        if desired <= 1:
            return [cleaned.strip()] if cleaned.strip() else [query]
        parts = re.split(r"\s+(?:vs|VS|versus)\s+|和|与|,|，|、", cleaned)
        targets = [part.strip(" 《》「」?？!！") for part in parts if part.strip(" 《》「」?？!！")]
        return targets[:desired] if targets else [query]

    async def _run_tool(
        self,
        ctx: AgentToolContext,
        name: str,
        trace_ctx: AgentStateContext,
        emit: Emit | None,
        **kwargs: Any,
    ) -> Any:
        summary = f"调用工具：{name}"
        trace_ctx.add_trace_step("tool_call", summary, tool_name=name, detail={"input": kwargs})
        await self._emit(emit, "tool_call", {"tool": name, "input": kwargs, "summary": summary, "trace_id": trace_ctx.trace_id})
        try:
            result = await execute_tool(ctx, name, **kwargs)
        except Exception as exc:
            trace_ctx.add_trace_step("observation", str(exc), tool_name=name, status="error")
            await self._emit(emit, "tool_error", {"tool": name, "message": str(exc), "trace_id": trace_ctx.trace_id})
            raise
        trace_ctx.add_trace_step("observation", f"{name} 返回成功。", tool_name=name)
        await self._emit(emit, "observation", {"tool": name, "summary": f"{name} 返回成功。", "trace_id": trace_ctx.trace_id})
        return result

    def _ensure_conversation(self, request: ChatRequest) -> Conversation:
        if request.conversation_id:
            conversation = self.session.get(Conversation, request.conversation_id)
            if conversation:
                return conversation
        title = request.query.strip()[:40] or "SteamAnalysis"
        conversation = Conversation(title=title)
        self.session.add(conversation)
        self.session.commit()
        self.session.refresh(conversation)
        return conversation

    def _record_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.session.add(
            Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                metadata_json=dump_json(metadata or {}),
                trace_id=trace_id,
            )
        )
        conversation = self.session.get(Conversation, conversation_id)
        if conversation:
            conversation.updated_at = utc_now()
        self.session.commit()

    async def _emit(self, emit: Emit | None, event: str, data: dict[str, Any]) -> None:
        if emit is not None:
            await emit(event, data)

    def _build_task_clarification(self, query: str, classification: TaskClassification) -> list[ClarificationOption]:
        if classification.confidence >= 0.72:
            return []
        desc_view = "查询 Steam 公开的游戏在线人数、价格等信息"
        desc_review = "分析最近用户评论的情绪和关键词"
        desc_compare = "对比两个游戏的在线人数和价格等数据"
        desc_sentiment = "从公开网页中分析游戏的社区评价和争议"
        return [
            ClarificationOption(label="查看游戏数据", description=desc_view, action_query=f"帮我看看 {query}"),
            ClarificationOption(label="分析游戏评论", description=desc_review, action_query=f"分析一下 {query} 的评论"),
            ClarificationOption(label="对比两个游戏", description=desc_compare, action_query=f"对比 {query}"),
            ClarificationOption(label="搜索网页舆情", description=desc_sentiment, action_query=f"搜索 {query} 的网页舆情"),
        ]

    def _extract_appids_from_results(self, results: list[dict]) -> list[int]:
        appids: list[int] = []
        for item in results:
            if item.get("kind") == "appid_resolved" and item.get("appid"):
                appids.append(item["appid"])
            elif item.get("kind") == "appids_resolved":
                appids.extend(item.get("appids", []))
        return appids

    def _snapshot_answer(self, snapshot: SnapshotRead, game_name: str | None) -> str:
        title = game_name or f"appid {snapshot.appid}"
        discount = snapshot.discount_percent or 0
        if snapshot.is_free:
            price_text = "当前标记为免费游戏。"
        elif discount > 0:
            price_text = f"当前有 {discount}% 折扣，价格字段来自 Steam Store appdetails。"
        elif snapshot.final_price is not None:
            price_text = "当前未看到折扣，价格字段来自 Steam Store appdetails。"
        else:
            price_text = "当前没有可用价格字段，可能是地区、下架或 Store API 返回差异导致。"
        players = (
            f"当前在线人数为 {snapshot.player_count:,}。"
            if snapshot.player_count is not None
            else "当前在线人数接口没有返回可用数值。"
        )
        return f"## {title}\n\n{players}\n\n{price_text}\n\n数据已保存为本地快照 `{snapshot.id}`。"

    def _snapshot_evidence(self, snapshot: SnapshotRead) -> list[AgentEvidence]:
        return [
            AgentEvidence(
                source="Steam GetNumberOfCurrentPlayers",
                url=snapshot.source_urls.get("current_players"),
                collected_at=snapshot.collected_at,
                summary=f"当前在线人数，本地快照 {snapshot.id}",
            ),
            AgentEvidence(
                source="Steam Store appdetails",
                url=snapshot.source_urls.get("store_appdetails"),
                collected_at=snapshot.collected_at,
                summary=f"基础信息、价格与折扣，本地快照 {snapshot.id}",
            ),
        ]

    def _game_name(self, appid: int) -> str | None:
        game = get_game_by_appid(self.session, appid)
        return game.name if game else None

    def _price_sentence(self, price: dict[str, Any]) -> str:
        if price.get("is_free"):
            return "免费游戏。"
        discount = price.get("discount_percent") or 0
        currency = price.get("currency") or price.get("cc") or ""
        final_price = price.get("final_price")
        if discount:
            return f"当前 {discount}% 折扣，最终价格字段为 {final_price} {currency}。"
        if final_price is not None:
            return f"当前未显示折扣，最终价格字段为 {final_price} {currency}。"
        return "暂无可用价格字段。"

    def _comparison_interpretation(self, comparison: dict[str, Any]) -> str:
        notes: list[str] = []
        for metric in comparison.get("metrics", []):
            field = metric.get("field")
            delta = metric.get("delta")
            if delta is None:
                continue
            if field == "player_count":
                if delta > 0:
                    notes.append(f"在线人数上升 {delta:,}，热度较左侧快照更高。")
                elif delta < 0:
                    notes.append(f"在线人数下降 {abs(delta):,}，可能是时间段或活动周期变化。")
            if field == "discount_percent" and delta:
                notes.append(f"折扣力度变化 {delta:+} 个百分点，价格上下文需要结合地区和币种判断。")
        return " ".join(notes) if notes else "当前只看到轻微或不可判定的数值差异，建议增加更多时间点后再下结论。"

    def _join_or_empty(self, values: list[str]) -> str:
        return "、".join(values) if values else "样本中未形成稳定关键词"

    def _build_clarification_candidates(self, uncertainties: list[str]) -> list[ClarificationOption]:
        candidates: list[ClarificationOption] = []
        seen: set[int] = set()
        for c in self._latest_search_candidates:
            appid = int(c.get("appid", 0))
            if appid and appid not in seen:
                seen.add(appid)
                name = c.get("name", f"appid {appid}")
                confidence = c.get("confidence", 0)
                candidates.append(
                    ClarificationOption(
                        label=f"{name} (appid {appid})",
                        description=f"Steam 搜索结果, 置信度 {confidence:.0%}",
                        action_query=f"帮我看看 {name}",
                    )
                )
        self._latest_search_candidates = []
        return candidates[:5]

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                normalized = value.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                return datetime.now(UTC)
        return datetime.now(UTC)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


async def answer(session: Session, steam: SteamClient, request: ChatRequest):
    """Run the agent state machine and return (conversation, report, result)."""
    machine = AgentStateMachine(session, steam)
    return await machine.handle(request)