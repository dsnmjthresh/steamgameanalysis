"""Background monitoring scheduler.

On startup loads all enabled ``monitor_tasks`` from the database and schedules
them via APScheduler.  Each job collects a fresh snapshot and evaluates alert
rules.  New tasks added via the API are picked up dynamically.

**Process separation**: The API process (``STEAMANALYSIS_ENABLE_SCHEDULER=false``)
does **not** run APScheduler.  Only the standalone worker process
(``python -m app.worker.scheduler``) starts the scheduler.  This avoids
duplicate job execution in multi-instance deployments.

For single-instance guarantees and health observability see
``ai-note/SCHEDULER_RUNBOOK.md``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session

from app.core.config import get_settings
from app.db.models import MonitorAlert, MonitorTask
from app.db.session import engine

logger = logging.getLogger("steamanalysis.scheduler")

_scheduler: BackgroundScheduler | None = None
_started_at: datetime | None = None
_health_file: str | None = None


# ---------------------------------------------------------------------------
# Job ID helpers (extracted for testability)
# ---------------------------------------------------------------------------


def make_monitor_job_id(appid: int, task_id: int) -> str:
    """Build a stable, deterministic job ID for a monitor task.

    The format is ``monitor_appid_{appid}_task_{task_id}``.  This function is
    the single source of truth — all scheduling, removal and health queries use
    it to construct or reconstruct the job ID.
    """
    return f"monitor_appid_{appid}_task_{task_id}"


def parse_monitor_job_id(job_id: str) -> tuple[int, int] | None:
    """Extract (appid, task_id) from a monitor job ID.

    Returns ``None`` for non-monitor job IDs (e.g. ``"memory_cleanup"``).
    """
    if not job_id.startswith("monitor_appid_"):
        return None
    parts = job_id[len("monitor_appid_"):].split("_task_")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Memory cleanup
# ---------------------------------------------------------------------------


def _cleanup_memory_job() -> None:
    """Periodic job: archive stale memory entries (low importance, not recently accessed)."""
    from app.services.memory_service import archive_stale_entries

    try:
        with Session(engine) as session:
            count = archive_stale_entries(session)
            if count:
                logger.info("archived %d stale memory entries", count)
    except Exception as exc:
        logger.warning("memory cleanup job failed: %s", exc)


# ---------------------------------------------------------------------------
# Alert rule evaluation
# ---------------------------------------------------------------------------


def _evaluate_alerts(appid: int, snapshot_id: int, session: Session) -> list[MonitorAlert]:
    """Run alert rules against the latest snapshot and return any triggered alerts."""
    alerts: list[MonitorAlert] = []

    # Load current snapshot
    from app.db.models import GameSnapshot

    current = session.get(GameSnapshot, snapshot_id)
    if current is None:
        return alerts

    # Load previous snapshots (last 10, excluding current)
    from sqlmodel import select

    previous = session.exec(
        select(GameSnapshot)
        .where(GameSnapshot.appid == appid, GameSnapshot.id != snapshot_id)
        .order_by(GameSnapshot.collected_at.desc())  # type: ignore[attr-defined]
        .limit(10)
    ).all()

    if not previous:
        return alerts

    # Recent average player count (last 5 snapshots, max 7 days old)
    now = datetime.now(UTC)
    recent = [
        s
        for s in previous[:5]
        if s.player_count is not None
        and (now - s.collected_at.replace(tzinfo=UTC)).total_seconds() < 7 * 86400
    ]
    if recent and current.player_count is not None:
        avg_players = sum(s.player_count or 0 for s in recent) / len(recent)
        if avg_players > 0:
            # Spike: > 1.5x recent average
            if current.player_count > avg_players * 1.5:
                alerts.append(
                    MonitorAlert(
                        appid=appid,
                        snapshot_id=snapshot_id,
                        alert_type="player_spike",
                        summary=f"在线人数暴涨：当前 {current.player_count:,}，近期均值 {avg_players:,.0f}",
                        severity="high",
                    )
                )
            # Drop: < 0.5x recent average
            elif current.player_count < avg_players * 0.5:
                alerts.append(
                    MonitorAlert(
                        appid=appid,
                        snapshot_id=snapshot_id,
                        alert_type="player_drop",
                        summary=f"在线人数下跌：当前 {current.player_count:,}，近期均值 {avg_players:,.0f}",
                        severity="high",
                    )
                )

    # Discount change detection
    prev_latest = previous[0]
    if (
        current.discount_percent is not None
        and prev_latest.discount_percent is not None
        and current.discount_percent != prev_latest.discount_percent
    ):
        alerts.append(
            MonitorAlert(
                appid=appid,
                snapshot_id=snapshot_id,
                alert_type="discount_change",
                summary=f"折扣变化：{prev_latest.discount_percent}% → {current.discount_percent}%",
                severity="medium",
            )
        )

    # New historical low price
    if current.final_price is not None:
        all_prices = [
            s.final_price
            for s in previous
            if s.final_price is not None and s.final_price > 0
        ]
        if all_prices and current.final_price > 0 and current.final_price < min(all_prices):
            alerts.append(
                MonitorAlert(
                    appid=appid,
                    snapshot_id=snapshot_id,
                    alert_type="new_lowest_price",
                    summary=(
                        f"新史低价格：当前 {_fmt_price(current.final_price, current.currency)}，"
                        f"此前最低 {_fmt_price(min(all_prices), current.currency)}"
                    ),
                    severity="medium",
                )
            )

    return alerts


def _fmt_price(price: int | None, currency: str | None) -> str:
    if price is None:
        return "N/A"
    curr = currency or "CNY"
    return f"{price / 100:.2f} {curr}"


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


def _execute_monitor_job(appid: int, task_id: int) -> None:
    """Collect a snapshot and evaluate alerts for one monitored game."""
    import asyncio as _asyncio

    logger.info("monitor job start: appid=%s task_id=%s", appid, task_id)

    async def _collect():
        from app.services.snapshot_service import collect_snapshot
        from app.services.steam_client import SteamClient

        settings = get_settings()
        async with SteamClient() as steam:
            with Session(engine) as session:
                # 1. Collect snapshot
                snapshot = await collect_snapshot(
                    session,
                    steam,
                    appid,
                    cc=settings.default_cc,
                    language=settings.default_language,
                )
                logger.info(
                    "monitor snapshot collected: appid=%s snapshot_id=%s players=%s",
                    appid,
                    snapshot.id,
                    snapshot.player_count,
                )

                # 2. Evaluate alerts
                if snapshot.id is not None:
                    new_alerts = _evaluate_alerts(appid, snapshot.id, session)
                    for alert in new_alerts:
                        session.add(alert)
                    if new_alerts:
                        logger.info(
                            "monitor alerts triggered: appid=%s count=%s",
                            appid,
                            len(new_alerts),
                        )
                    session.commit()

                # 3. Update last_run_at
                task = session.get(MonitorTask, task_id)
                if task is not None:
                    task.last_run_at = datetime.now(UTC)
                    session.add(task)
                    session.commit()

    try:
        _asyncio.run(_collect())
    except Exception:
        logger.exception("monitor job failed: appid=%s task_id=%s", appid, task_id)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------


def start_scheduler() -> BackgroundScheduler:
    """Load enabled tasks from DB and start the APScheduler.

    Returns the scheduler instance so the caller can shut it down on exit.
    Writes the initial health file if one has been configured via
    :func:`configure_health_file`.
    """
    global _scheduler, _started_at

    _scheduler = BackgroundScheduler(
        daemon=True,
        timezone="UTC",
        job_defaults={"misfire_grace_time": 300, "coalesce": True},
    )

    # Load existing tasks
    monitor_task_count = 0
    with Session(engine) as session:
        from sqlmodel import select

        tasks = session.exec(
            select(MonitorTask).where(MonitorTask.enabled.is_(True))  # type: ignore[attr-defined]
        ).all()

        for task in tasks:
            if task.id is None:
                continue
            job_id = make_monitor_job_id(task.appid, task.id)
            if _scheduler.get_job(job_id):
                logger.warning("duplicate job skipped: job_id=%s", job_id)
                continue
            _scheduler.add_job(
                _execute_monitor_job,
                trigger=IntervalTrigger(minutes=max(task.interval_minutes, 5)),
                args=[task.appid, task.id],
                id=job_id,
                name=f"Monitor appid={task.appid}",
                replace_existing=True,
            )
            logger.info(
                "scheduled monitor: appid=%s interval=%smin job_id=%s",
                task.appid,
                task.interval_minutes,
                job_id,
            )
            monitor_task_count += 1

    # Register periodic memory cleanup (every 6 hours)
    _scheduler.add_job(
        _cleanup_memory_job,
        trigger=IntervalTrigger(hours=6),
        id="memory_cleanup",
        name="Memory stale entry archival",
        replace_existing=True,
    )

    _scheduler.start()
    _started_at = datetime.now(UTC)

    total_jobs = len(_scheduler.get_jobs())
    logger.info(
        "scheduler started: monitor_tasks=%d total_jobs=%d started_at=%s pid=%d",
        monitor_task_count,
        total_jobs,
        _started_at.isoformat(),
        os.getpid(),
    )

    # Write initial health file
    _write_health_file()

    return _scheduler


def get_scheduler() -> BackgroundScheduler | None:
    """Return the global scheduler instance (may be None if not started)."""
    return _scheduler


def add_monitor_job(appid: int, task_id: int, interval_minutes: int) -> bool:
    """Dynamically add a new monitor job to the running scheduler."""
    if _scheduler is None:
        return False
    job_id = make_monitor_job_id(appid, task_id)
    try:
        _scheduler.add_job(
            _execute_monitor_job,
            trigger=IntervalTrigger(minutes=max(interval_minutes, 5)),
            args=[appid, task_id],
            id=job_id,
            name=f"Monitor appid={appid}",
            replace_existing=True,
        )
        logger.info("dynamic monitor added: appid=%s interval=%smin job_id=%s", appid, interval_minutes, job_id)
        _write_health_file()
        return True
    except Exception:
        logger.exception("failed to add dynamic monitor: appid=%s", appid)
        return False


def remove_monitor_job(appid: int, task_id: int) -> bool:
    """Remove a monitor job from the running scheduler."""
    if _scheduler is None:
        return False
    job_id = make_monitor_job_id(appid, task_id)
    try:
        _scheduler.remove_job(job_id)
        logger.info("dynamic monitor removed: appid=%s job_id=%s", appid, job_id)
        _write_health_file()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Health & observability
# ---------------------------------------------------------------------------


def get_scheduler_health() -> dict:
    """Return scheduler health state for observability.

    Returns a dict with keys:
      - ``running``: whether the scheduler is running (bool)
      - ``job_count``: total number of scheduled jobs (int)
      - ``monitor_job_count``: subset of jobs that are monitor tasks (int)
      - ``jobs``: list of dicts with id, name, next_run_time
      - ``started_at``: ISO-8601 timestamp or None
      - ``pid``: OS process ID or None
      - ``health_file``: configured health file path or None
    """
    global _scheduler, _started_at, _health_file

    if _scheduler is None:
        return {
            "running": False,
            "job_count": 0,
            "monitor_job_count": 0,
            "jobs": [],
            "started_at": None,
            "pid": None,
            "health_file": _health_file,
        }

    all_jobs = _scheduler.get_jobs()
    jobs_list = []
    monitor_count = 0
    for job in all_jobs:
        entry = {
            "id": job.id,
            "name": job.name or "",
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        jobs_list.append(entry)
        if parse_monitor_job_id(job.id) is not None:
            monitor_count += 1

    return {
        "running": _scheduler.running,
        "job_count": len(all_jobs),
        "monitor_job_count": monitor_count,
        "jobs": jobs_list,
        "started_at": _started_at.isoformat() if _started_at else None,
        "pid": os.getpid(),
        "health_file": _health_file,
    }


def configure_health_file(path: str) -> None:
    """Set the scheduler health file path.

    When configured, the scheduler writes a JSON health snapshot to this file
    on every state change (start, add, remove, heartbeat).  External monitoring
    (Docker healthcheck, status CLI, monitoring daemon) can read this file to
    determine whether the scheduler is alive and what it is running.

    Only the standalone worker process should call this.  The API process does
    not configure a health file because it does not own the scheduler.
    """
    global _health_file
    _health_file = path
    logger.info("scheduler health file configured: %s", path)


def write_health_file() -> bool:
    """Atomically write current health state to the configured health file.

    Returns True on success, False if no health file is configured or the
    write fails.  This is public so the worker process can call it on a
    periodic heartbeat.
    """
    global _health_file
    if not _health_file:
        return False
    try:
        health = get_scheduler_health()
        # Use a temp file + rename for atomicity
        tmp = _health_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(health, f, ensure_ascii=False, default=str)
        os.replace(tmp, _health_file)
        return True
    except Exception:
        logger.warning("Failed to write scheduler health file %s", _health_file, exc_info=True)
        return False


def _write_health_file() -> None:
    """Internal: best-effort write of health file (never raises)."""
    write_health_file()


def _remove_health_file() -> None:
    """Remove the health file on clean shutdown."""
    global _health_file
    if not _health_file:
        return
    try:
        os.remove(_health_file)
        logger.info("scheduler health file removed: %s", _health_file)
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("Failed to remove scheduler health file %s", _health_file, exc_info=True)


def stop_scheduler() -> None:
    """Shut down the scheduler and clean up resources.

    Removes the health file, shuts down APScheduler, and resets globals.
    Safe to call even if the scheduler was never started.
    """
    global _scheduler, _started_at, _health_file

    _remove_health_file()
    _health_file = None

    if _scheduler is not None:
        logger.info("shutting down scheduler (pid=%d)…", os.getpid())
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            logger.warning("error during scheduler shutdown", exc_info=True)
        _scheduler = None

    _started_at = None
    logger.info("scheduler stopped")
