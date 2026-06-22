"""Tests for task queue internals — handler registration, worker processing,
async bridging, and claim mechanics.

These tests cover the code paths that were added or changed during the
``review_analyze`` handler fix.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session

from app.db.models import BackgroundTask
from app.services import task_queue as tq

# ============================================================================
# Handler registration
# ============================================================================


def test_all_expected_handler_types_are_registered():
    """Verify the four task types that the UI creates are all registered."""
    from app.services.task_queue import _TASK_HANDLERS

    assert "web_sentiment" in _TASK_HANDLERS
    assert "batch_snapshot" in _TASK_HANDLERS
    assert "report_generate" in _TASK_HANDLERS
    assert "review_analyze" in _TASK_HANDLERS


def test_unregistered_task_type_fails_cleanly(session: Session):
    """An unregistered task type is failed with UNREGISTERED_TASK_TYPE."""
    task = tq.enqueue_task(
        session,
        task_type="nonexistent_xyz",
        input_data={"x": 1},
        trace_id="trace-unreg",
    )

    # Simulate what the worker does when handler is missing
    handler = tq._TASK_HANDLERS.get(task.task_type)
    assert handler is None
    tq.fail_task(session, task.id or 0, f"未注册的 task_type: {task.task_type}", error_code="UNREGISTERED_TASK_TYPE")

    session.refresh(task)
    assert task.status == "failed"
    code, _ = tq._parse_error_db(task.error_message)
    assert code == "UNREGISTERED_TASK_TYPE"


def test_enqueue_then_fail_pending(session: Session):
    """pending → failed transition is allowed (for unregistered types, bad input)."""
    task = tq.enqueue_task(session, task_type="web_sentiment", input_data={})
    assert task.status == "pending"

    tq.fail_task(session, task.id or 0, "bad input", error_code="BAD_INPUT")
    session.refresh(task)
    assert task.status == "failed"


# ============================================================================
# Async bridge helper
# ============================================================================


def test_run_async_in_handler_no_running_loop():
    """_run_async_in_handler works when no event loop is running (asyncio.run)."""
    called = False

    async def _test():
        nonlocal called
        called = True
        return 42

    result = tq._run_async_in_handler(_test)
    assert result == 42
    assert called


def test_run_async_in_handler_with_running_loop():
    """_run_async_in_handler works inside a running event loop (thread fallback)."""
    async def _work():
        called_inner = False

        async def _inner():
            nonlocal called_inner
            called_inner = True
            return "from-inner"

        result = tq._run_async_in_handler(_inner)
        assert result == "from-inner"
        assert called_inner
        return "ok"

    got = asyncio.run(_work())
    assert got == "ok"


def test_run_async_in_handler_propagates_exception():
    """_run_async_in_handler propagates exceptions from the async function."""
    async def _failing():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        tq._run_async_in_handler(_failing)


# ============================================================================
# Worker claim mechanics
# ============================================================================


def test_claim_task_transitions_pending_to_running(session: Session):
    """_claim_task moves a pending task to running."""
    task = tq.enqueue_task(session, task_type="web_sentiment", input_data={"query": "test"})
    assert task.status == "pending"

    claimed = tq._claim_task(session, task)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.started_at is not None


def test_claim_task_returns_none_for_non_pending(session: Session):
    """_claim_task returns None if the task is no longer pending."""
    task = tq.enqueue_task(session, task_type="web_sentiment", input_data={"query": "test"})
    # Manually set to running (simulating race)
    task.status = "running"
    session.add(task)
    session.commit()

    claimed = tq._claim_task(session, task)
    assert claimed is None


def test_claim_task_idempotent_under_race(session: Session):
    """Two consecutive claims on the same task: second returns None."""
    task = tq.enqueue_task(session, task_type="web_sentiment", input_data={"query": "test"})

    first = tq._claim_task(session, task)
    assert first is not None
    assert first.status == "running"

    # Now simulate a concurrent worker trying to claim the same task
    second = tq._claim_task(session, task)
    assert second is None


# ============================================================================
# Worker batch processing (_process_pending)
# ============================================================================


def test_process_pending_handles_multiple_tasks(session: Session):
    """_process_pending processes all pending tasks in one iteration."""
    tq.enqueue_task(session, task_type="web_sentiment", input_data={"query": "q1"})
    tq.enqueue_task(session, task_type="web_sentiment", input_data={"query": "q2"})
    tq.enqueue_task(session, task_type="web_sentiment", input_data={"query": "q3"})

    # Verify all 3 are pending
    from sqlmodel import select
    pending_before = list(session.exec(
        select(BackgroundTask).where(BackgroundTask.status == "pending")
    ).all())
    assert len(pending_before) == 3

    # Mock the handler to return success
    original = tq._TASK_HANDLERS.get("web_sentiment")
    try:
        tq._TASK_HANDLERS["web_sentiment"] = lambda s, t, **kw: {"ok": True}
        processed = tq._process_pending(session)
        assert processed == 3
    finally:
        if original:
            tq._TASK_HANDLERS["web_sentiment"] = original

    # All should now be completed
    completed = list(session.exec(
        select(BackgroundTask).where(BackgroundTask.status == "completed")
    ).all())
    assert len(completed) == 3


def test_process_pending_skips_unregistered_type(session: Session):
    """_process_pending fails tasks with unregistered types."""
    task = tq.enqueue_task(session, task_type="bad_type_xyz", input_data={"x": 1})

    processed = tq._process_pending(session)
    assert processed >= 1

    session.refresh(task)
    assert task.status == "failed"
    code, _ = tq._parse_error_db(task.error_message)
    assert code == "UNREGISTERED_TASK_TYPE"


def test_process_pending_empty_queue(session: Session):
    """_process_pending returns 0 when no pending tasks."""
    processed = tq._process_pending(session)
    assert processed == 0


# ============================================================================
# review_analyze handler
# ============================================================================


def _claim_and_call(session: Session, task: BackgroundTask, handler, **input_data):
    """Helper: claim a task to 'running', then invoke its handler.

    Mimics what _process_pending does before calling each handler.
    """
    claimed = tq._claim_task(session, task)
    assert claimed is not None, "Could not claim task — is it already claimed?"
    return handler(session, task, **input_data)


def test_review_analyze_handler_missing_appid(session: Session):
    """review_analyze without appid fails with MISSING_APPID."""
    task = tq.enqueue_task(session, task_type="review_analyze", input_data={"query": "test"})

    handler = tq._TASK_HANDLERS["review_analyze"]
    result = _claim_and_call(session, task, handler, **{"query": "test"})  # no appid

    session.refresh(task)
    assert task.status == "failed"
    code, _ = tq._parse_error_db(task.error_message)
    assert code == "MISSING_APPID"
    assert result is None


@patch("app.services.review_service.ReviewService")
@patch("app.services.steam_client.SteamClient")
def test_review_analyze_handler_success(mock_steam_cls, mock_service_cls, session: Session):
    """review_analyze handler fetches, analyzes, and saves reviews."""
    from datetime import UTC, datetime

    # Setup mock SteamClient as a proper async context manager
    mock_steam = MagicMock()
    mock_steam.__aenter__ = AsyncMock(return_value=mock_steam)
    mock_steam.__aexit__ = AsyncMock(return_value=None)
    mock_steam_cls.return_value = mock_steam

    # Setup mock ReviewService
    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service

    # Mock fetch_reviews to return a coroutine
    mock_fetch = AsyncMock(return_value=(
        [
            MagicMock(
                voted_up=True, review_text="Great game!", language="schinese",
                timestamp_created=datetime.now(UTC),
            ),
        ],
        "https://steamcommunity.com/app/730/reviews/",
        None,
    ))
    mock_service.fetch_reviews = mock_fetch

    # Mock analyze_sentiment_llm
    from app.schemas.review import SentimentAnalysisResult
    analysis_result = SentimentAnalysisResult(
        appid=730, total_reviews=1, positive_ratio=1.0,
        top_praise_keywords=["fun"], top_complaint_keywords=[],
        summary="Great reviews",
        source_url="https://steamcommunity.com/app/730/reviews/",
        analyzed_at=datetime.now(UTC), reviews=[],
    )
    mock_service.analyze_sentiment_llm = AsyncMock(return_value=analysis_result)
    mock_service.save_analysis = MagicMock()

    task = tq.enqueue_task(
        session, task_type="review_analyze",
        input_data={"appid": 730, "query": "test", "count": 10},
    )

    handler = tq._TASK_HANDLERS["review_analyze"]
    result = _claim_and_call(session, task, handler, appid=730, query="test", count=10)

    session.refresh(task)
    assert task.status == "completed"
    assert result is None  # handler called complete_task itself

    # Verify result data
    parsed = json.loads(task.result_json or "{}")
    assert parsed["appid"] == 730
    assert parsed["total_reviews"] == 1
    assert parsed["positive_ratio"] == 1.0


@patch("app.services.review_service.ReviewService")
@patch("app.services.steam_client.SteamClient")
def test_review_analyze_handler_cancellation(mock_steam_cls, mock_service_cls, session: Session):
    """review_analyze handler respects cancellation before starting work."""
    mock_steam = MagicMock()
    mock_steam.__aenter__ = AsyncMock(return_value=mock_steam)
    mock_steam.__aexit__ = AsyncMock(return_value=None)
    mock_steam_cls.return_value = mock_steam

    task = tq.enqueue_task(
        session, task_type="review_analyze",
        input_data={"appid": 730, "query": "test"},
    )
    # Cancel the task before the handler runs
    tq.cancel_task(session, task.id or 0)

    handler = tq._TASK_HANDLERS["review_analyze"]
    # Don't claim — task is already cancelled (terminal)
    handler(session, task, appid=730, query="test")

    session.refresh(task)
    assert task.status == "cancelled"  # Handler detects it and leaves it


@patch("app.services.review_service.ReviewService")
@patch("app.services.steam_client.SteamClient")
def test_review_analyze_handler_cancelled_does_not_fail(mock_steam_cls, mock_service_cls, session: Session):
    """Cancellation is a real cancelled terminal state, not failed/CANCELLED."""
    mock_steam = MagicMock()
    mock_steam.__aenter__ = AsyncMock(return_value=mock_steam)
    mock_steam.__aexit__ = AsyncMock(return_value=None)
    mock_steam_cls.return_value = mock_steam

    task = tq.enqueue_task(
        session, task_type="review_analyze",
        input_data={"appid": 730, "query": "test"},
    )
    tq.cancel_task(session, task.id or 0)

    handler = tq._TASK_HANDLERS["review_analyze"]
    handler(session, task, appid=730, query="test")

    session.refresh(task)
    assert task.status == "cancelled"
    assert task.error_message is None


# ============================================================================
# report_generate handler (existing — verify it still works after refactor)
# ============================================================================


def test_report_generate_handler_without_appid(session: Session):
    """report_generate without appid still completes with minimal data."""
    task = tq.enqueue_task(
        session, task_type="report_generate",
        input_data={"query": "test query", "appid": None},
    )

    handler = tq._TASK_HANDLERS["report_generate"]
    _claim_and_call(session, task, handler, query="test query", appid=None)

    session.refresh(task)
    # Should complete with "无足够数据生成报告" message
    assert task.status == "completed"


# ============================================================================
# Worker start/stop lifecycle (require async fixtures)
# ============================================================================


@pytest.mark.anyio
async def test_start_worker_creates_task():
    """start_worker creates an asyncio Task."""
    tq.stop_worker()  # Ensure clean state
    tq._worker_task = None
    tq._worker_running = False

    def fake_factory():
        class _Fake:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
        return _Fake()

    tq.start_worker(fake_factory)
    assert tq._worker_task is not None
    assert not tq._worker_task.done()

    tq.stop_worker()
    # Let the cancelled task settle
    await asyncio.sleep(0.05)


@pytest.mark.anyio
async def test_start_worker_idempotent():
    """Calling start_worker twice does not create a second task."""
    tq.stop_worker()
    tq._worker_task = None
    tq._worker_running = False

    def fake_factory():
        class _Fake:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
        return _Fake()

    tq.start_worker(fake_factory)
    first = tq._worker_task

    tq.start_worker(fake_factory)
    assert tq._worker_task is first  # Same task, not replaced

    tq.stop_worker()
    await asyncio.sleep(0.05)


# ============================================================================
# Progress update guards
# ============================================================================


def test_update_progress_clamps_to_100(session: Session):
    """update_task_progress clamps to 0–100 range."""
    task = tq.enqueue_task(session, task_type="web_sentiment", input_data={})
    tq._claim_task(session, task)

    tq.update_task_progress(session, task.id or 0, 150.0, "over")
    session.refresh(task)
    assert task.progress_pct == 100.0

    tq.update_task_progress(session, task.id or 0, -10.0, "under")
    session.refresh(task)
    assert task.progress_pct == 0.0


def test_progress_message_truncated(session: Session):
    """progress_message is truncated to 256 chars."""
    task = tq.enqueue_task(session, task_type="web_sentiment", input_data={})
    tq._claim_task(session, task)

    long_msg = "x" * 500
    tq.update_task_progress(session, task.id or 0, 50.0, long_msg)

    session.refresh(task)
    assert len(task.progress_message or "") <= 256
