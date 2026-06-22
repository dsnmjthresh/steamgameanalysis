"""Tests for /api/tasks endpoints — enqueue, poll, cancel, list.

Covers:
- Basic CRUD (create, poll, cancel, list)
- State machine guards (illegal transitions rejected)
- Cancellation semantics (pending, running, terminal)
- Structured error output (error_code, error_message, trace_id)
- List filtering by status and task_type
"""

import json
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.core.config import Settings
from app.db.models import BackgroundTask
from app.services import task_queue as tq

_AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _patched_settings() -> Settings:
    """Settings with auth token configured for tests."""
    return Settings(auth_token="test-token")


def _seed_task(
    session: Session,
    task_type: str = "web_sentiment",
    status: str = "pending",
    progress_pct: float = 0,
    result_json: str | None = None,
    input_json: str | None = None,
    error_message: str | None = None,
    trace_id: str | None = "trace-001",
) -> BackgroundTask:
    task = BackgroundTask(
        task_type=task_type,
        status=status,
        progress_pct=progress_pct,
        progress_message="processing...",
        input_json=input_json or json.dumps({"query": "test query"}),
        result_json=result_json,
        error_message=error_message,
        trace_id=trace_id,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# ============================================================================
# Basic CRUD (existing coverage, preserved)
# ============================================================================


@pytest.mark.anyio
async def test_create_task_returns_202(client):
    """POST /api/tasks creates a task and returns 202."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/tasks",
            json={
                "task_type": "web_sentiment",
                "input_data": {"query": "CS2 更新后玩家评价"},
            },
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["task_type"] == "web_sentiment"
    assert body["status"] == "pending"
    assert body["progress_pct"] == 0
    assert "id" in body
    assert body["trace_id"] is not None  # trace_id assigned on enqueue


@pytest.mark.anyio
async def test_create_task_without_task_type_rejects(client):
    """POST /api/tasks without task_type returns 422."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/tasks",
            json={"input_data": {}},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_task_unknown_task_type_rejects(client):
    """POST /api/tasks rejects unknown task_type before enqueueing."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/tasks",
            json={"task_type": "bad_type_xyz", "input_data": {"query": "test"}},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_batch_snapshot_rejects_more_than_50_appids(client):
    """batch_snapshot has an explicit 50-appid upper bound."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/tasks",
            json={"task_type": "batch_snapshot", "input_data": {"appids": list(range(1, 52))}},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_review_analyze_requires_appid(client):
    """review_analyze validates required appid at the API boundary."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/tasks",
            json={"task_type": "review_analyze", "input_data": {"query": "reviews"}},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_poll_task_returns_status(client, session):
    """GET /api/tasks/{task_id} returns current task status."""
    task = _seed_task(session, status="running", progress_pct=50)

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            f"/api/tasks/{task.id}",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == task.id
    assert body["status"] == "running"
    assert body["progress_pct"] == 50
    assert body["trace_id"] == "trace-001"


@pytest.mark.anyio
async def test_poll_nonexistent_task_returns_404(client):
    """GET /api/tasks/99999 returns 404."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            "/api/tasks/99999",
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_cancel_task_sets_status_cancelled(client, session):
    """POST /api/tasks/{task_id}/cancel sets pending task to cancelled."""
    task = _seed_task(session, status="pending")

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            f"/api/tasks/{task.id}/cancel",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None


@pytest.mark.anyio
async def test_cancel_nonexistent_task_returns_404(client):
    """POST /api/tasks/99999/cancel returns 404."""
    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            "/api/tasks/99999/cancel",
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_list_tasks_returns_all(client, session):
    """GET /api/tasks returns list of tasks."""
    _seed_task(session, task_type="web_sentiment", status="completed", progress_pct=100)
    _seed_task(session, task_type="report_generate", status="pending")

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            "/api/tasks",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 2


@pytest.mark.anyio
async def test_list_tasks_filters_by_status(client, session):
    """GET /api/tasks?status=pending filters correctly."""
    _seed_task(session, status="completed", progress_pct=100)
    _seed_task(session, status="pending")
    _seed_task(session, status="pending")

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            "/api/tasks",
            params={"status": "pending"},
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert all(t["status"] == "pending" for t in body)


@pytest.mark.anyio
async def test_list_tasks_filters_by_task_type(client, session):
    """GET /api/tasks?task_type=report_generate filters correctly."""
    _seed_task(session, task_type="web_sentiment", status="pending")
    _seed_task(session, task_type="report_generate", status="pending")

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            "/api/tasks",
            params={"task_type": "report_generate"},
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert all(t["task_type"] == "report_generate" for t in body)


@pytest.mark.anyio
async def test_completed_task_has_result_data(client, session):
    """Completed tasks expose result_data."""
    _seed_task(
        session,
        status="completed",
        progress_pct=100,
        result_json=json.dumps({"sentiment": "negative", "score": -0.5}),
    )

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            "/api/tasks",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    completed = [t for t in body if t["status"] == "completed"]
    assert len(completed) >= 1
    assert "sentiment" in completed[0]["result_data"]


# ============================================================================
# State machine guards — illegal transitions
# ============================================================================


def test_cannot_complete_already_completed_task(session):
    """complete_task on an already-completed task is a no-op."""
    task = _seed_task(
        session,
        status="completed",
        progress_pct=100,
        result_json=json.dumps({"original": "data"}),
    )

    result = tq.complete_task(session, task.id or 0, {"new": "data"})
    assert result is not None
    assert result.status == "completed"  # unchanged
    assert result.result_json is not None
    # Result data should NOT have been overwritten
    parsed = json.loads(result.result_json)
    assert parsed.get("original") == "data"
    assert "new" not in parsed


def test_cannot_fail_already_completed_task(session):
    """fail_task on an already-completed task is a no-op."""
    task = _seed_task(
        session,
        status="completed",
        progress_pct=100,
        result_json=json.dumps({"score": 100}),
    )

    result = tq.fail_task(session, task.id or 0, "should not apply")
    assert result is not None
    assert result.status == "completed"  # unchanged
    parsed = json.loads(result.result_json or "{}")
    assert parsed.get("score") == 100


def test_cannot_complete_failed_task(session):
    """complete_task on a failed task is a no-op."""
    task = _seed_task(session, status="failed", error_message='{"error_code":"TEST","detail":"fail"}')

    result = tq.complete_task(session, task.id or 0, {"new": "data"})
    assert result is not None
    assert result.status == "failed"  # unchanged


def test_cannot_fail_cancelled_task(session):
    """fail_task on a cancelled task is a no-op."""
    task = _seed_task(session, status="cancelled")

    result = tq.fail_task(session, task.id or 0, "should not apply")
    assert result is not None
    assert result.status == "cancelled"  # unchanged


def test_cannot_update_progress_on_terminal_task(session):
    """update_task_progress on a completed task is rejected."""
    task = _seed_task(session, status="completed", progress_pct=100)

    result = tq.update_task_progress(session, task.id or 0, 50.0, "updating?")
    assert result is not None
    assert result.progress_pct == 100  # unchanged


def test_transition_from_pending_to_running(session):
    """The worker claims a pending task → running (valid transition).

    ``pending → failed`` is also allowed so the worker can fail tasks
    immediately for unrecoverable reasons (unregistered type, bad input).
    """
    task = _seed_task(session, status="pending")
    assert tq._check_transition(task, "running") is True
    assert tq._check_transition(task, "cancelled") is True
    assert tq._check_transition(task, "failed") is True
    # Cannot jump directly from pending to completed
    assert tq._check_transition(task, "completed") is False


def test_transition_from_running(session):
    """A running task can go to completed, failed, or cancelled."""
    task = _seed_task(session, status="running")
    assert tq._check_transition(task, "completed") is True
    assert tq._check_transition(task, "failed") is True
    assert tq._check_transition(task, "cancelled") is True
    # Cannot go back to pending
    assert tq._check_transition(task, "pending") is False
    assert tq._check_transition(task, "running") is False


def test_terminal_states_have_no_valid_transitions(session):
    """completed, failed, cancelled should reject any further transitions."""
    for state in ["completed", "failed", "cancelled"]:
        task = _seed_task(session, status=state)
        for target in ["pending", "running", "completed", "failed", "cancelled"]:
            assert tq._check_transition(task, target) is False, (
                f"Transition {state}→{target} should be forbidden"
            )


# ============================================================================
# Cancel semantics
# ============================================================================


def test_cancel_pending_task_service(session):
    """Service layer: cancel a pending task."""
    task = _seed_task(session, status="pending")
    result = tq.cancel_task(session, task.id or 0)
    assert result is not None
    assert result.status == "cancelled"
    assert result.cancelled_at is not None


def test_cancel_running_task_service(session):
    """Service layer: cancel a running task (marks cancelled)."""
    task = _seed_task(session, status="running")
    result = tq.cancel_task(session, task.id or 0)
    assert result is not None
    assert result.status == "cancelled"


def test_cancel_completed_task_preserves_result(session):
    """Cancelling a completed task returns it unchanged — no state mutation."""
    original_result = json.dumps({"sentiment": "positive", "score": 0.8})
    task = _seed_task(
        session,
        status="completed",
        progress_pct=100,
        result_json=original_result,
    )

    result = tq.cancel_task(session, task.id or 0)
    assert result is not None
    assert result.status == "completed"  # unchanged
    assert result.result_json == original_result  # data preserved
    assert result.progress_pct == 100  # progress preserved


def test_cancel_failed_task_preserves_error(session):
    """Cancelling a failed task returns it unchanged."""
    task = _seed_task(
        session,
        status="failed",
        error_message=tq._format_error_db("Steam API timeout", "STEAM_API_TIMEOUT"),
    )

    result = tq.cancel_task(session, task.id or 0)
    assert result is not None
    assert result.status == "failed"  # unchanged


@pytest.mark.anyio
async def test_cancel_completed_task_api_preserves_result(client, session):
    """API: POST /cancel on completed task returns 200 with unchanged data."""
    task = _seed_task(
        session,
        status="completed",
        progress_pct=100,
        result_json=json.dumps({"sentiment": "positive"}),
    )

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.post(
            f"/api/tasks/{task.id}/cancel",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"  # unchanged
    assert body["result_data"]["sentiment"] == "positive"


def test_is_cancelled_detection(session):
    """is_cancelled() returns True for cancelled tasks, False otherwise."""
    pending = _seed_task(session, status="pending")
    running = _seed_task(session, status="running")
    cancelled = _seed_task(session, status="cancelled")

    assert tq.is_cancelled(session, pending.id or 0) is False
    assert tq.is_cancelled(session, running.id or 0) is False
    assert tq.is_cancelled(session, cancelled.id or 0) is True


# ============================================================================
# Structured error output
# ============================================================================


def test_fail_task_with_error_code(session):
    """fail_task stores structured error_code in error_message JSON."""
    task = _seed_task(session, status="running")

    tq.fail_task(session, task.id or 0, "Steam API 超时", error_code="STEAM_API_TIMEOUT")
    session.refresh(task)

    assert task.status == "failed"
    assert task.error_message is not None
    # Verify structured storage
    code, detail = tq._parse_error_db(task.error_message)
    assert code == "STEAM_API_TIMEOUT"
    assert "Steam API" in (detail or "")


def test_fail_task_without_error_code_uses_unknown(session):
    """fail_task without error_code defaults to UNKNOWN."""
    task = _seed_task(session, status="running")

    tq.fail_task(session, task.id or 0, "Something broke")
    session.refresh(task)

    code, detail = tq._parse_error_db(task.error_message)
    assert code == "UNKNOWN"
    assert "Something broke" in (detail or "")


def test_parse_error_db_legacy_plain_text(session):
    """_parse_error_db falls back gracefully for legacy plain-text errors."""
    code, detail = tq._parse_error_db("just a plain error string")
    assert code is None
    assert detail == "just a plain error string"


def test_parse_error_db_empty(session):
    """_parse_error_db returns None,None for empty input."""
    code, detail = tq._parse_error_db(None)
    assert code is None
    assert detail is None


@pytest.mark.anyio
async def test_failed_task_api_exposes_error_code(client, session):
    """API response for a failed task includes error_code and error_message."""
    task = _seed_task(
        session,
        status="failed",
        error_message=tq._format_error_db("Connection timed out", "STEAM_API_TIMEOUT"),
    )

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            f"/api/tasks/{task.id}",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "STEAM_API_TIMEOUT"
    assert "Connection timed out" in (body["error_message"] or "")


@pytest.mark.anyio
async def test_failed_task_api_exposes_trace_id(client, session):
    """Failed task response includes trace_id for log correlation."""
    task = _seed_task(
        session,
        status="failed",
        error_message=tq._format_error_db("Boom", "CRASH"),
        trace_id="trace-abc123",
    )

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            f"/api/tasks/{task.id}",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == "trace-abc123"
    assert body["error_code"] == "CRASH"


@pytest.mark.anyio
async def test_completed_task_has_null_error_code(client, session):
    """Completed tasks should not have error_code set."""
    task = _seed_task(
        session,
        status="completed",
        progress_pct=100,
        result_json=json.dumps({"ok": True}),
    )

    with patch("app.core.config.get_settings", return_value=_patched_settings()):
        response = await client.get(
            f"/api/tasks/{task.id}",
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["error_code"] is None
    assert body["error_message"] is None


# ============================================================================
# Enqueue / transition integration
# ============================================================================


def test_enqueue_task_sets_fields(session):
    """enqueue_task sets correct initial state."""
    task = tq.enqueue_task(
        session,
        task_type="batch_snapshot",
        input_data={"appids": [730, 570]},
        trace_id="custom-trace",
    )
    assert task.status == "pending"
    assert task.progress_pct == 0.0
    assert task.progress_message == "已加入队列"
    assert task.trace_id == "custom-trace"
    assert task.started_at is None
    assert task.completed_at is None
    assert task.cancelled_at is None


def test_complete_task_sets_terminal_fields(session):
    """complete_task sets completed_at and 100% progress."""
    task = _seed_task(session, status="running", progress_pct=50)

    result = tq.complete_task(session, task.id or 0, {"done": True})
    assert result is not None
    assert result.status == "completed"
    assert result.progress_pct == 100.0
    assert result.completed_at is not None


def test_fail_task_sets_completed_at(session):
    """fail_task sets completed_at timestamp."""
    task = _seed_task(session, status="running")

    result = tq.fail_task(session, task.id or 0, "error", error_code="TEST")
    assert result is not None
    assert result.status == "failed"
    assert result.completed_at is not None


# ============================================================================
# Double-cancel idempotency
# ============================================================================


def test_double_cancel_pending_is_idempotent(session):
    """Cancelling an already-cancelled pending task is idempotent."""
    task = _seed_task(session, status="pending")

    first = tq.cancel_task(session, task.id or 0)
    assert first is not None
    assert first.status == "cancelled"

    second = tq.cancel_task(session, task.id or 0)
    assert second is not None
    assert second.status == "cancelled"
    # Terminal state — second cancel should be a no-op that returns unchanged


def test_double_cancel_running_is_idempotent(session):
    """Cancelling a task that was already cancelled during 'running' is idempotent."""
    task = _seed_task(session, status="running")

    first = tq.cancel_task(session, task.id or 0)
    assert first.status == "cancelled"

    second = tq.cancel_task(session, task.id or 0)
    assert second.status == "cancelled"  # still cancelled
