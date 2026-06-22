"""Tests for the Agent self-reflection loop in AgentStateMachine."""

from unittest.mock import AsyncMock, MagicMock

from app.agent.runtime import AgentStateContext, AgentStateMachine
from app.schemas.chat import AgentAnalysisResult
from app.services.steam_client import SteamClient


def _make_machine():
    """Create a state machine with mocked session and steam client."""
    session = MagicMock()
    steam = AsyncMock(spec=SteamClient)
    machine = AgentStateMachine(session, steam)
    # Mock classifier to avoid real LLM calls
    machine.classifier = AsyncMock()
    from app.agent.task_classifier import TaskClassification

    machine.classifier.classify = AsyncMock(
        return_value=TaskClassification(
            task_type="single_game",
            reason="test",
            confidence=0.9,
            source="heuristic",
        )
    )
    return machine, session, steam


def _make_ctx(machine):
    """Create a minimal context for testing."""
    from app.agent.runtime import RuntimeTrace

    return AgentStateContext(
        session=machine.session,
        steam=machine.steam,
        trace_id="test-trace",
        trace=RuntimeTrace(),
    )


def test_no_reflection_when_no_issues():
    """_should_reflect returns False when there are no previous issues."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx.result = AgentAnalysisResult(
        task_type="single_game",
        answer="test answer",
        uncertainties=[],
    )
    ctx._previous_issues = []

    assert machine._should_reflect(ctx) is False


def test_no_reflection_when_mild_issues():
    """_should_reflect returns False when issues exist but are not significant."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx.result = AgentAnalysisResult(
        task_type="single_game",
        answer="test answer",
        uncertainties=["数据可能不是最新的。", "价格信息仅供参考。"],
    )
    ctx._previous_issues = ctx.result.uncertainties

    assert machine._should_reflect(ctx) is False


def test_reflection_when_significant_issues():
    """_should_reflect returns True when >=2 significant issues exist."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx.result = AgentAnalysisResult(
        task_type="single_game",
        answer="test answer",
        uncertainties=[
            "缺少在线人数数据。",
            "未找到价格信息。",
        ],
    )
    ctx._previous_issues = ctx.result.uncertainties

    assert machine._should_reflect(ctx) is True
    assert ctx.result is None  # result cleared for re-synthesis


def test_max_loops_respected():
    """_should_reflect returns False when max loops reached."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx._reflection_count = 3  # equals MAX_REFLECTION_LOOPS
    ctx.result = AgentAnalysisResult(
        task_type="single_game",
        answer="test answer",
        uncertainties=["缺少数据。", "未找到信息。"],
    )
    ctx._previous_issues = ctx.result.uncertainties

    assert machine._should_reflect(ctx) is False


def test_no_reflection_when_no_result():
    """_should_reflect returns False when ctx.result is None."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx.result = None
    ctx._previous_issues = ["缺少数据。", "未找到信息。"]

    assert machine._should_reflect(ctx) is False


def test_reflection_clears_result():
    """When reflection triggers, ctx.result is set to None."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx.result = AgentAnalysisResult(
        task_type="single_game",
        answer="test answer",
        uncertainties=["缺少在线人数。", "未获取到价格数据。"],
    )
    ctx._previous_issues = ctx.result.uncertainties

    assert ctx.result is not None
    result = machine._should_reflect(ctx)
    assert result is True
    assert ctx.result is None


def test_not_enough_significant_issues():
    """Reflection not triggered with only 1 significant issue (< REFLECTION_THRESHOLD=2)."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx.result = AgentAnalysisResult(
        task_type="single_game",
        answer="test answer",
        uncertainties=["数据缺少具体数字。"],
    )
    ctx._previous_issues = ctx.result.uncertainties

    assert machine._should_reflect(ctx) is False


def test_chinese_issue_keywords_trigger_reflection():
    """Chinese keywords like 缺少 and 不足 trigger reflection."""
    machine, _, _ = _make_machine()
    ctx = _make_ctx(machine)
    ctx.result = AgentAnalysisResult(
        task_type="single_game",
        answer="test answer",
        uncertainties=["缺少玩家数据。", "价格不足够明确。"],
    )
    ctx._previous_issues = ctx.result.uncertainties

    assert machine._should_reflect(ctx) is True
