"""Background task queue backed by SQLite.

Provides:
- ``enqueue_task`` — create a new task (returns task id)
- ``poll_task`` — fetch current task status for frontend polling
- ``cancel_task`` — mark a pending/running task as cancelled
- ``update_task_progress`` — update progress during execution
- ``complete_task`` / ``fail_task`` — terminal state transitions
- ``list_tasks`` — list tasks for a user or by status
- ``run_worker`` — asyncio background loop that picks up pending tasks

State Machine
-------------

.. code-block::

    pending ──► running ──► completed
      │            │            (terminal)
      │            ├──► failed
      │            │    (terminal)
      │            ├──► cancelled
      │            │    (terminal)
      ├────────────┘──► cancelled
      │                 (terminal)
      └──────────────► failed
                       (terminal: unregistered type, bad input)

Terminal states (completed / failed / cancelled) cannot be modified.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlmodel import Session, select

from app.core.logging import get_request_id
from app.db.models import BackgroundTask, utc_now
from app.schemas.common import dump_json
from app.services.steam_client import SteamClient

logger = logging.getLogger("steamanalysis.task_queue")

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),  # terminal
    "failed": frozenset(),  # terminal
    "cancelled": frozenset(),  # terminal
}


def _check_transition(task: BackgroundTask, new_status: str) -> bool:
    """Return True if the state transition is allowed."""
    allowed = VALID_TRANSITIONS.get(task.status, frozenset())
    return new_status in allowed


def _get_task_fresh(session: Session, task_id: int) -> BackgroundTask | None:
    """Load a task row while bypassing the Session identity-map cache.

    Background handlers keep a session open while the user may cancel the same
    task through another request/session.  ``Session.get()`` can otherwise
    return a stale in-memory object and allow a cancelled task to continue into
    ``completed``.
    """
    try:
        return session.get(BackgroundTask, task_id, populate_existing=True)
    except TypeError:
        task = session.get(BackgroundTask, task_id)
        if task is not None:
            try:
                session.refresh(task)
            except Exception:
                pass
        return task


# ---------------------------------------------------------------------------
# Structured error helpers (no new DB fields — stores JSON in error_message)
# ---------------------------------------------------------------------------

_ERROR_STRUCTURE_KEYS = {"error_code", "detail"}


def _format_error_db(error: str, error_code: str | None = None) -> str:
    """Pack error + optional error_code into structured JSON for the
    ``error_message`` database column.

    This avoids adding ``error_code`` as a separate DB field.
    """
    return dump_json({
        "error_code": error_code or "UNKNOWN",
        "detail": error,
    })


def _parse_error_db(
    error_message: str | None,
) -> tuple[str | None, str | None]:
    """Parse a structured ``error_message`` back into
    ``(error_code, human_readable_detail)``.

    Returns ``(None, error_message)`` for legacy plain-text messages.
    """
    if not error_message:
        return None, None
    try:
        parsed = json.loads(error_message)
    except json.JSONDecodeError:
        return None, error_message
    if isinstance(parsed, dict) and _ERROR_STRUCTURE_KEYS.issubset(parsed.keys()):
        return parsed.get("error_code"), parsed.get("detail", error_message)
    return None, error_message


# ---------------------------------------------------------------------------
# Task type handlers — register new task types here
# ---------------------------------------------------------------------------

_TASK_HANDLERS: dict[str, Any] = {}


def register_handler(task_type: str):
    """Decorator to register a coroutine as a task type handler.

    The handler receives ``(session, task, **parsed_input)`` and must
    call ``update_task_progress`` / ``complete_task`` / ``fail_task`` itself.
    """
    def decorator(func):
        _TASK_HANDLERS[task_type] = func
        return func
    return decorator


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def enqueue_task(
    session: Session,
    task_type: str,
    input_data: dict[str, Any],
    user_id: int | None = None,
    trace_id: str | None = None,
) -> BackgroundTask:
    task = BackgroundTask(
        user_id=user_id,
        task_type=task_type,
        status="pending",
        progress_pct=0.0,
        progress_message="已加入队列",
        input_json=dump_json(input_data),
        trace_id=trace_id or get_request_id(),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info("Enqueued task %d type=%s trace_id=%s", task.id, task_type, task.trace_id)
    return task


def poll_task(session: Session, task_id: int) -> BackgroundTask | None:
    return session.get(BackgroundTask, task_id)


def update_task_progress(
    session: Session,
    task_id: int,
    progress_pct: float,
    message: str = "",
) -> BackgroundTask | None:
    task = _get_task_fresh(session, task_id)
    if task is None:
        return None
    # Refuse to update progress for terminal tasks
    if task.status in TERMINAL_STATES:
        logger.warning(
            "Task %d: refusing progress update (terminal state %s)",
            task_id, task.status,
        )
        return task
    task.progress_pct = max(0.0, min(100.0, progress_pct))
    if message:
        task.progress_message = message[:256]
    session.add(task)
    session.commit()
    return task


def complete_task(
    session: Session,
    task_id: int,
    result: dict[str, Any],
) -> BackgroundTask | None:
    task = _get_task_fresh(session, task_id)
    if task is None:
        return None
    if not _check_transition(task, "completed"):
        logger.warning(
            "Task %d: refused transition %s→completed",
            task_id, task.status,
        )
        return task  # No-op — return current state unchanged
    task.status = "completed"
    task.progress_pct = 100.0
    task.progress_message = "任务完成"
    task.result_json = dump_json(result)
    task.completed_at = utc_now()
    session.add(task)
    session.commit()
    logger.info("Task %d completed", task_id)
    return task


def fail_task(
    session: Session,
    task_id: int,
    error: str,
    error_code: str | None = None,
) -> BackgroundTask | None:
    task = _get_task_fresh(session, task_id)
    if task is None:
        return None
    if not _check_transition(task, "failed"):
        logger.warning(
            "Task %d: refused transition %s→failed",
            task_id, task.status,
        )
        return task  # No-op — return current state unchanged
    task.status = "failed"
    task.error_message = _format_error_db(error[:2000], error_code)
    task.completed_at = utc_now()
    session.add(task)
    session.commit()
    logger.error("Task %d failed code=%s: %s", task_id, error_code or "UNKNOWN", error[:120])
    return task


def cancel_task(session: Session, task_id: int) -> BackgroundTask | None:
    """Cancel a pending or running task.

    - *pending* → cancelled immediately.
    - *running* → marked cancelled; handler is expected to poll ``is_cancelled()``
      and abort cooperatively.
    - Terminal states → returned unchanged (no error, no state mutation).
    """
    task = _get_task_fresh(session, task_id)
    if task is None:
        return None
    if task.status in TERMINAL_STATES:
        logger.info(
            "Task %d cancel ignored — already terminal (%s)",
            task_id, task.status,
        )
        return task
    previous = task.status
    task.status = "cancelled"
    task.cancelled_at = utc_now()
    task.completed_at = task.cancelled_at
    task.progress_message = "已取消"
    session.add(task)
    session.commit()
    logger.info(
        "Task %d cancelled (was %s)",
        task_id, previous,
    )
    return task


def is_cancelled(session: Session, task_id: int) -> bool:
    """Check whether a task has been cancelled (for handler cooperative abort).

    Handlers for long-running operations should call this periodically and
    abort early when it returns ``True``.
    """
    task = _get_task_fresh(session, task_id)
    return task is not None and task.status == "cancelled"


def list_tasks(
    session: Session,
    user_id: int | None = None,
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 20,
) -> list[BackgroundTask]:
    statement = select(BackgroundTask).order_by(BackgroundTask.created_at.desc())  # type: ignore[attr-defined]
    if user_id is not None:
        statement = statement.where(BackgroundTask.user_id == user_id)
    if status is not None:
        statement = statement.where(BackgroundTask.status == status)
    if task_type is not None:
        statement = statement.where(BackgroundTask.task_type == task_type)
    return list(session.exec(statement.limit(limit)).all())


# ---------------------------------------------------------------------------
# Async bridge helper — shared by all handlers that need to run async code
# ---------------------------------------------------------------------------


def _run_async_in_handler(async_func):
    """Bridge an async callable into the sync handler context.

    Detects whether an asyncio event loop is already running and uses the
    appropriate strategy:
    - No running loop → ``asyncio.run()`` (creates a fresh loop)
    - Running loop → spawn a daemon thread with its own loop

    Returns the result of ``await async_func()``.
    """
    import asyncio as _asyncio

    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return _asyncio.run(async_func())

    # Inside an async context — run on a dedicated thread
    import concurrent.futures as _cf

    future: _cf.Future = _cf.Future()

    def _runner():
        try:
            future.set_result(_asyncio.run(async_func()))
        except Exception as exc:
            future.set_exception(exc)

    import threading as _threading
    _threading.Thread(target=_runner, daemon=True).start()
    return future.result()


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

_worker_running = False
_worker_task: asyncio.Task | None = None


async def run_worker(session_factory, poll_interval_s: float = 2.0) -> None:
    """Background worker that processes pending tasks.

    Call ``start_worker(session_factory)`` during app startup.
    Call ``stop_worker()`` during app shutdown.

    Processes ALL pending tasks each iteration (not just one) so that bursts
    of task creation don't leave tasks sitting in the queue unnecessarily.
    """
    global _worker_running
    _worker_running = True
    logger.info("Background task worker started (poll interval %.1fs)", poll_interval_s)

    while _worker_running:
        processed = 0
        try:
            with session_factory() as session:
                processed = _process_pending(session)
        except Exception:
            logger.exception("Worker iteration error")
        if processed > 0:
            logger.debug("Worker processed %d task(s) this iteration", processed)
        await asyncio.sleep(poll_interval_s)

    logger.info("Background task worker stopped")


def _claim_task(session: Session, task: BackgroundTask) -> BackgroundTask | None:
    """Atomically claim a pending task by transitioning it to 'running'.

    Uses a SELECT + UPDATE double-check pattern to prevent duplicate pickup
    when multiple workers share the same database.
    """
    task_id = task.id or 0

    claimed: BackgroundTask | None = session.exec(
        select(BackgroundTask).where(
            BackgroundTask.id == task_id,
            BackgroundTask.status == "pending",
        )
    ).first()

    if claimed is None:
        return None  # Another worker already picked it up

    if not _check_transition(claimed, "running"):
        logger.warning("Task %d: cannot transition %s→running", task_id, claimed.status)
        return None

    claimed.status = "running"
    claimed.started_at = utc_now()
    claimed.progress_message = "开始执行"
    session.add(claimed)
    session.commit()
    return claimed


def _process_pending(session: Session) -> int:
    """Pick up and execute ALL pending tasks in-order.

    Returns the number of tasks processed (including those that failed).
    """
    tasks: list[BackgroundTask] = list(
        session.exec(
            select(BackgroundTask)
            .where(BackgroundTask.status == "pending")
            .order_by(BackgroundTask.created_at.asc())  # type: ignore[attr-defined]
            .limit(20)  # upper bound per iteration to avoid starvation
        ).all()
    )

    processed = 0
    for task in tasks:
        task_id = task.id or 0
        task_type = task.task_type

        handler = _TASK_HANDLERS.get(task_type)
        if handler is None:
            fail_task(session, task_id, f"未注册的 task_type: {task_type}", error_code="UNREGISTERED_TASK_TYPE")
            processed += 1
            continue

        claimed = _claim_task(session, task)
        if claimed is None:
            continue  # Raced — skip

        try:
            input_data = json.loads(task.input_json or "{}")
        except json.JSONDecodeError:
            fail_task(session, task_id, "无法解析 input_json", error_code="INVALID_INPUT_JSON")
            processed += 1
            continue

        try:
            result = handler(session, task, **input_data)
            if result is not None:
                # Handler returned data — complete the task
                complete_task(session, task_id, result)
        except Exception as exc:
            fail_task(session, task_id, str(exc), error_code="HANDLER_EXCEPTION")

        processed += 1

    return processed


def start_worker(session_factory) -> None:
    """Start the background worker as an asyncio task."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        logger.warning("Worker already running — skipping duplicate start")
        return
    _worker_task = asyncio.ensure_future(run_worker(session_factory))
    logger.info("Background task worker asyncio task created")


def stop_worker() -> None:
    """Stop the background worker gracefully."""
    global _worker_running, _worker_task
    _worker_running = False
    if _worker_task is not None:
        _worker_task.cancel()
        _worker_task = None


# ---------------------------------------------------------------------------
# Built-in task handlers
# ---------------------------------------------------------------------------


def _confirm_cancelled(session: Session, task_id: int) -> BackgroundTask | None:
    """Ensure a task is in the real ``cancelled`` terminal state."""
    task = _get_task_fresh(session, task_id)
    if task is None:
        return None
    if task.status == "cancelled":
        return task
    if task.status in TERMINAL_STATES:
        return task
    return cancel_task(session, task_id)


# ---------- web_sentiment ----------


@register_handler("web_sentiment")
def _handle_web_sentiment(
    session: Session,
    task: BackgroundTask,
    query: str = "",
    game: str | None = None,
    appid: int | None = None,
    limit: int = 5,
) -> dict[str, Any] | None:
    """Run web sentiment analysis in the background."""
    from app.schemas.web_sentiment import WebSentimentRequest
    from app.services.web_sentiment_service import WebSentimentService

    task_id = task.id or 0

    async def _run():
        if is_cancelled(session, task_id):
            _confirm_cancelled(session, task_id)
            return {"cancelled": True}
        update_task_progress(session, task_id, 10.0, "正在搜索网页...")
        result = await WebSentimentService().analyze(
            session,
            WebSentimentRequest(
                game=game, query=query, appid=appid, limit=limit,
                persist_to_knowledge=True,
            ),
        )
        if is_cancelled(session, task_id):
            _confirm_cancelled(session, task_id)
            return {"cancelled": True}
        update_task_progress(session, task_id, 90.0, "正在持久化结果...")
        return result.model_dump(mode="json")

    result = _run_async_in_handler(_run)
    if isinstance(result, dict) and result.get("cancelled"):
        return None  # fail_task already called
    complete_task(session, task_id, result)
    return None


# ---------- batch_snapshot ----------


@register_handler("batch_snapshot")
def _handle_batch_snapshot(
    session: Session,
    task: BackgroundTask,
    appids: list[int],
    cc: str | None = None,
    language: str | None = None,
) -> dict[str, Any] | None:
    """Collect snapshots for multiple appids.

    Checks cancellation between each appid so the user can stop a long batch
    early without losing already-collected data.
    """
    from app.services.snapshot_service import collect_snapshot

    task_id = task.id or 0
    total = len(appids)
    results: list[dict] = []
    errors: list[dict] = []
    cancelled = False

    async def _collect():
        nonlocal cancelled
        async with SteamClient() as steam:
            for idx, appid in enumerate(appids):
                if is_cancelled(session, task_id):
                    cancelled = True
                    break
                progress = (idx / max(total, 1)) * 90.0
                update_task_progress(session, task_id, progress, f"采集 {appid} ({idx + 1}/{total})")
                try:
                    snap = await collect_snapshot(
                        session=session, steam=steam, appid=appid,
                        cc=cc, language=language, labels=[],
                    )
                    results.append({"appid": appid, "snapshot_id": snap.id, "status": "ok"})
                except Exception as exc:
                    errors.append({"appid": appid, "error": str(exc)})
                    update_task_progress(session, task_id, progress, f"采集 {appid} 失败: {exc}")

    _run_async_in_handler(_collect)

    out = {
        "snapshots": results,
        "errors": errors,
        "total": total,
        "succeeded": len(results),
        "cancelled": cancelled,
    }
    if cancelled:
        _confirm_cancelled(session, task_id)
        return None
    complete_task(session, task_id, out)
    return None


# ---------- report_generate ----------


@register_handler("report_generate")
def _handle_report_generate(
    session: Session,
    task: BackgroundTask,
    query: str = "",
    appid: int | None = None,
) -> dict[str, Any] | None:
    """Generate an analysis report in the background.

    Phases: trend analysis → review analysis → report generation.
    Checks cancellation between phases.
    """
    from app.services.report_service import create_report
    from app.services.review_service import ReviewService
    from app.services.snapshot_service import analyze_snapshot_trend

    task_id = task.id or 0
    report_data: dict[str, Any] = {"query": query, "appid": appid}

    try:
        # ---- Phase 1: Trend analysis ----
        if is_cancelled(session, task_id):
            _confirm_cancelled(session, task_id)
            return None
        update_task_progress(session, task_id, 20.0, "正在分析趋势数据...")
        if appid:
            trend = analyze_snapshot_trend(session, appid=appid, days=30)
            report_data["trend_summary"] = trend.summary
            report_data["snapshot_count"] = trend.snapshot_count

        # ---- Phase 2: Review analysis ----
        if is_cancelled(session, task_id):
            _confirm_cancelled(session, task_id)
            return None
        update_task_progress(session, task_id, 60.0, "正在分析评论...")
        if appid:
            async def _review_analysis():
                async with SteamClient() as steam:
                    service = ReviewService()
                    reviews, source_url, _ = await service.fetch_reviews(
                        steam, appid=appid, count=100,
                    )
                    result = await service.analyze_sentiment_llm(
                        appid=appid, reviews=reviews, source_url=source_url,
                    )
                    return result

            review_result = _run_async_in_handler(_review_analysis)
            report_data["review_summary"] = review_result.summary
            report_data["positive_ratio"] = review_result.positive_ratio

        # ---- Phase 3: Report generation ----
        if is_cancelled(session, task_id):
            _confirm_cancelled(session, task_id)
            return None
        update_task_progress(session, task_id, 85.0, "正在生成报告...")

        answer = f"## {query}\n\n"
        if "trend_summary" in report_data:
            answer += f"### 趋势\n{report_data['trend_summary']}\n\n"
        if "review_summary" in report_data:
            answer += f"### 评论分析\n{report_data['review_summary']}\n\n"
        if not report_data.get("trend_summary") and not report_data.get("review_summary"):
            answer += "无足够数据生成报告。"

        create_report(
            session, query=query, answer_markdown=answer,
            structured_result=report_data, evidence=[], snapshot_ids=[],
        )
        complete_task(session, task_id, report_data)
        return None

    except Exception as exc:
        fail_task(session, task_id, str(exc), error_code="REPORT_GENERATE_FAILED")
        return None


# ---------- review_analyze ----------


@register_handler("review_analyze")
def _handle_review_analyze(
    session: Session,
    task: BackgroundTask,
    appid: int | None = None,
    query: str = "",
    count: int = 100,
    review_type: str = "all",
    language: str = "schinese",
    days: int = 0,
) -> dict[str, Any] | None:
    """Analyze Steam reviews for a game in the background.

    Fetches reviews via Steam API, runs LLM-enhanced sentiment + topic
    extraction, persists results to the database, and returns a summary.

    Parameters (from input_data):
        appid: Steam App ID (required)
        query: user's original question for context
        count: number of reviews to fetch (default 100)
        review_type: "all", "positive", or "negative"
        language: Steam review language code (default "schinese")
        days: time window in days (0 = no filter)
    """
    if not appid:
        fail_task(session, task.id or 0, "缺少 appid 参数", error_code="MISSING_APPID")
        return None

    task_id = task.id or 0
    from app.services.review_service import ReviewService
    from app.services.steam_client import SteamClient

    async def _run():
        # ---- Phase 1: Fetch and analyze ----
        if is_cancelled(session, task_id):
            _confirm_cancelled(session, task_id)
            return {"cancelled": True}

        update_task_progress(session, task_id, 15.0, f"正在获取 {appid} 的评论...")

        async with SteamClient() as steam:
            service = ReviewService()

            if is_cancelled(session, task_id):
                _confirm_cancelled(session, task_id)
                return {"cancelled": True}

            # Fetch reviews
            reviews, source_url, raw = await service.fetch_reviews(
                steam, appid=appid, language=language, count=count,
            )
            update_task_progress(session, task_id, 40.0, f"已获取 {len(reviews)} 条评论，正在分析...")

            if is_cancelled(session, task_id):
                _confirm_cancelled(session, task_id)
                return {"cancelled": True}

            # Analyze with LLM + rule fallback
            result = await service.analyze_sentiment_llm(
                appid=appid, reviews=reviews, source_url=source_url,
            )

            update_task_progress(session, task_id, 75.0, "正在保存分析结果...")

            if is_cancelled(session, task_id):
                _confirm_cancelled(session, task_id)
                return {"cancelled": True}

            # Persist to DB
            service.save_analysis(session, result)

            update_task_progress(session, task_id, 95.0, "正在整理输出...")

            return {
                "appid": appid,
                "total_reviews": result.total_reviews,
                "positive_ratio": result.positive_ratio,
                "top_praise": result.top_praise_keywords,
                "top_complaints": result.top_complaint_keywords,
                "summary": result.summary,
                "source_url": result.source_url,
                "analyzed_at": result.analyzed_at.isoformat() if result.analyzed_at else None,
                "query": query,
            }

    result = _run_async_in_handler(_run)
    if isinstance(result, dict) and result.get("cancelled"):
        return None
    complete_task(session, task_id, result)
    return None
