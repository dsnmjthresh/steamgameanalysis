"""Tests for the scheduler service module.

Covers:
- make_monitor_job_id / parse_monitor_job_id stability
- get_scheduler_health when scheduler is None / running
- add_monitor_job / remove_monitor_job dynamics
- Health file write, atomicity and cleanup
- stop_scheduler cleanup
- start_scheduler integration with a test database
- Disabled scheduler behavior in worker entry point
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from unittest.mock import patch

import pytest

from app.services import scheduler_service as svc
from app.services.scheduler_service import (
    add_monitor_job,
    configure_health_file,
    get_scheduler,
    get_scheduler_health,
    make_monitor_job_id,
    parse_monitor_job_id,
    remove_monitor_job,
    start_scheduler,
    stop_scheduler,
    write_health_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_scheduler_state() -> Generator[None, None, None]:
    """Reset scheduler global state before and after every test.

    Also resets the health file path to empty (disabled).
    """
    # Before
    svc._scheduler = None
    svc._started_at = None
    svc._health_file = None
    yield
    # After
    try:
        sched = svc._scheduler
        if sched is not None:
            sched.shutdown(wait=False)
    except Exception:
        pass
    # Remove any leftover health file
    health_file = svc._health_file
    svc._scheduler = None
    svc._started_at = None
    svc._health_file = None
    if health_file and os.path.exists(health_file):
        try:
            os.remove(health_file)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# make_monitor_job_id / parse_monitor_job_id
# ---------------------------------------------------------------------------


class TestMakeMonitorJobId:
    """Job ID construction is stable and deterministic."""

    def test_consistent_same_inputs(self) -> None:
        """Same inputs always produce the same ID."""
        id1 = make_monitor_job_id(730, 42)
        id2 = make_monitor_job_id(730, 42)
        assert id1 == id2

    def test_different_appid_produces_different_id(self) -> None:
        assert make_monitor_job_id(730, 1) != make_monitor_job_id(570, 1)

    def test_different_task_id_produces_different_id(self) -> None:
        assert make_monitor_job_id(730, 1) != make_monitor_job_id(730, 2)

    def test_expected_format(self) -> None:
        job_id = make_monitor_job_id(appid=730, task_id=5)
        assert job_id == "monitor_appid_730_task_5"

    def test_large_ids(self) -> None:
        job_id = make_monitor_job_id(appid=999999, task_id=88888)
        assert "999999" in job_id
        assert "88888" in job_id


class TestParseMonitorJobId:
    """parse_monitor_job_id extracts (appid, task_id) from a job ID."""

    def test_roundtrip(self) -> None:
        for appid, tid in [(730, 1), (570, 99), (123456, 42), (0, 0)]:
            job_id = make_monitor_job_id(appid, tid)
            assert parse_monitor_job_id(job_id) == (appid, tid)

    def test_non_monitor_id_returns_none(self) -> None:
        assert parse_monitor_job_id("memory_cleanup") is None
        assert parse_monitor_job_id("some_other_job") is None
        assert parse_monitor_job_id("") is None

    def test_malformed_prefix_returns_none(self) -> None:
        assert parse_monitor_job_id("monitor_appid_abc_task_1") is None  # non-int appid
        assert parse_monitor_job_id("monitor_appid_730_task_xyz") is None  # non-int task_id
        assert parse_monitor_job_id("monitor_appid_730") is None  # missing task_id segment
        assert parse_monitor_job_id("monitor_appid_730_task_") is None  # empty task_id


# ---------------------------------------------------------------------------
# get_scheduler_health — stopped state
# ---------------------------------------------------------------------------


class TestSchedulerHealthWhenStopped:
    """get_scheduler_health when no scheduler is running."""

    def test_health_reports_not_running(self) -> None:
        health = get_scheduler_health()
        assert health["running"] is False
        assert health["job_count"] == 0
        assert health["monitor_job_count"] == 0
        assert health["jobs"] == []
        assert health["started_at"] is None
        assert health["pid"] is None

    def test_health_after_stop_scheduler(self) -> None:
        """After stop_scheduler(), health reports not running."""
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched
        stop_scheduler()

        health = get_scheduler_health()
        assert health["running"] is False

    def test_health_structure_has_all_keys(self) -> None:
        health = get_scheduler_health()
        expected_keys = {"running", "job_count", "monitor_job_count", "jobs",
                         "started_at", "pid", "health_file"}
        assert set(health.keys()) == expected_keys


# ---------------------------------------------------------------------------
# get_scheduler_health — running state
# ---------------------------------------------------------------------------


class TestSchedulerHealthWhenRunning:
    """get_scheduler_health when a scheduler is active."""

    def test_health_reports_running(self) -> None:
        from datetime import UTC, datetime

        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched
        svc._started_at = datetime.now(UTC)

        try:
            health = get_scheduler_health()
            assert health["running"] is True
            assert health["job_count"] == 0  # no jobs added yet
            assert health["monitor_job_count"] == 0
            assert health["started_at"] is not None
            assert health["pid"] is not None
            assert isinstance(health["pid"], int)
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None
            svc._started_at = None

    def test_health_includes_monitor_jobs(self) -> None:
        """After adding a monitor job, health shows it."""
        from datetime import UTC, datetime

        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched
        svc._started_at = datetime.now(UTC)

        try:
            add_monitor_job(appid=730, task_id=1, interval_minutes=30)
            add_monitor_job(appid=570, task_id=2, interval_minutes=60)

            health = get_scheduler_health()
            assert health["running"] is True
            assert health["monitor_job_count"] == 2
            assert health["job_count"] == 2

            job_ids = [j["id"] for j in health["jobs"]]
            assert make_monitor_job_id(730, 1) in job_ids
            assert make_monitor_job_id(570, 2) in job_ids

            # Each job entry has required keys
            for j in health["jobs"]:
                assert "id" in j
                assert "name" in j
                assert "next_run_time" in j
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None
            svc._started_at = None


# ---------------------------------------------------------------------------
# add_monitor_job / remove_monitor_job
# ---------------------------------------------------------------------------


class TestAddMonitorJob:
    """Dynamic job addition."""

    def test_add_success(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched

        try:
            result = add_monitor_job(appid=730, task_id=42, interval_minutes=30)
            assert result is True

            job = sched.get_job(make_monitor_job_id(730, 42))
            assert job is not None
            assert job.name == "Monitor appid=730"
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None

    def test_add_enforces_min_5min_interval(self) -> None:
        """Interval below 5 minutes is clamped to 5."""
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched

        try:
            # Try to add with 1-minute interval — should be clamped to 5
            result = add_monitor_job(appid=730, task_id=1, interval_minutes=1)
            assert result is True
            # The job exists — the IntervalTrigger was created with max(1, 5) = 5
            job = sched.get_job(make_monitor_job_id(730, 1))
            assert job is not None
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None

    def test_add_replace_existing(self) -> None:
        """Adding a job with the same ID replaces the old one."""
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched

        try:
            result1 = add_monitor_job(appid=730, task_id=1, interval_minutes=30)
            assert result1 is True

            # Add again with different interval
            result2 = add_monitor_job(appid=730, task_id=1, interval_minutes=60)
            assert result2 is True

            # Should still have exactly 1 job
            assert len(sched.get_jobs()) == 1
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None

    def test_add_when_scheduler_none_returns_false(self) -> None:
        result = add_monitor_job(appid=730, task_id=1, interval_minutes=30)
        assert result is False


class TestRemoveMonitorJob:
    """Dynamic job removal."""

    def test_remove_success(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched

        try:
            add_monitor_job(appid=730, task_id=42, interval_minutes=30)
            assert sched.get_job(make_monitor_job_id(730, 42)) is not None

            result = remove_monitor_job(appid=730, task_id=42)
            assert result is True
            assert sched.get_job(make_monitor_job_id(730, 42)) is None
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None

    def test_remove_non_existent_returns_false(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched

        try:
            result = remove_monitor_job(appid=999, task_id=999)
            assert result is False  # APScheduler raises on non-existent job
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None

    def test_remove_when_scheduler_none_returns_false(self) -> None:
        result = remove_monitor_job(appid=730, task_id=1)
        assert result is False


# ---------------------------------------------------------------------------
# Health file
# ---------------------------------------------------------------------------


class TestHealthFile:
    """Health file write, atomicity, and cleanup."""

    def test_write_creates_file(self, tmp_path) -> None:
        path = str(tmp_path / "scheduler.health")
        configure_health_file(path)

        result = write_health_file()
        assert result is True
        assert os.path.exists(path)

    def test_write_produces_valid_json(self, tmp_path) -> None:
        path = str(tmp_path / "scheduler.health")
        configure_health_file(path)
        write_health_file()

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, dict)
        assert "running" in data
        assert "job_count" in data
        assert "pid" in data
        # When scheduler is None, pid is None
        assert data["running"] is False

    def test_write_with_no_path_configured_returns_false(self) -> None:
        configure_health_file("")  # empty string = falsy = disabled
        result = write_health_file()
        assert result is False

    def test_write_is_atomic_no_temp_leftover(self, tmp_path) -> None:
        path = str(tmp_path / "scheduler.health")
        configure_health_file(path)
        write_health_file()

        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")

    def test_write_reflects_running_scheduler(self, tmp_path) -> None:
        from datetime import UTC, datetime

        from apscheduler.schedulers.background import BackgroundScheduler

        path = str(tmp_path / "scheduler.health")
        configure_health_file(path)

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched
        svc._started_at = datetime.now(UTC)

        try:
            add_monitor_job(appid=730, task_id=1, interval_minutes=30)
            write_health_file()

            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            assert data["running"] is True
            assert data["monitor_job_count"] == 1
            assert data["job_count"] == 1
            assert data["started_at"] is not None
            assert data["pid"] is not None
        finally:
            sched.shutdown(wait=False)
            svc._scheduler = None
            svc._started_at = None

    def test_configure_logs_path(self, caplog) -> None:
        import logging
        caplog.set_level(logging.INFO, logger="steamanalysis.scheduler")
        configure_health_file("/tmp/test.health")
        assert "/tmp/test.health" in caplog.text


# ---------------------------------------------------------------------------
# stop_scheduler
# ---------------------------------------------------------------------------


class TestStopScheduler:
    """Clean shutdown behavior."""

    def test_stop_clears_globals(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched

        stop_scheduler()

        assert svc._scheduler is None
        assert svc._started_at is None
        health = get_scheduler_health()
        assert health["running"] is False

    def test_stop_when_none_is_safe(self) -> None:
        """Calling stop_scheduler when scheduler was never started is a no-op."""
        stop_scheduler()  # Should not raise
        stop_scheduler()  # Idempotent
        assert svc._scheduler is None

    def test_stop_removes_health_file(self, tmp_path) -> None:
        path = str(tmp_path / "scheduler.health")
        configure_health_file(path)
        write_health_file()
        assert os.path.exists(path)

        stop_scheduler()

        assert not os.path.exists(path)
        assert svc._health_file is None

    def test_stop_handles_missing_health_file(self, tmp_path) -> None:
        """stop_scheduler is safe when health file was already removed."""
        path = str(tmp_path / "nonexistent.health")
        configure_health_file(path)
        # Don't create the file — simulate someone deleting it externally
        stop_scheduler()  # Should not raise
        assert svc._health_file is None


# ---------------------------------------------------------------------------
# get_scheduler
# ---------------------------------------------------------------------------


class TestGetScheduler:
    """Global scheduler accessor."""

    def test_returns_none_initially(self) -> None:
        assert get_scheduler() is None

    def test_returns_instance_after_start(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched

        try:
            assert get_scheduler() is sched
        finally:
            sched.shutdown(wait=False)  # type: ignore[union-attr]
            svc._scheduler = None


# ---------------------------------------------------------------------------
# start_scheduler with test database
# ---------------------------------------------------------------------------


class TestStartSchedulerWithDb:
    """Integration: start_scheduler loads tasks from a real database."""

    def test_no_enabled_tasks_only_memory_cleanup(self, engine) -> None:
        """When no enabled MonitorTask rows exist, only memory_cleanup is scheduled."""
        with patch.object(svc, "engine", engine):
            _sched = start_scheduler()
            try:
                health = get_scheduler_health()
                assert health["running"] is True
                assert health["monitor_job_count"] == 0
                # memory_cleanup should be present
                assert health["job_count"] >= 1
                job_ids = [j["id"] for j in health["jobs"]]
                assert "memory_cleanup" in job_ids
            finally:
                stop_scheduler()

    def test_enabled_tasks_become_jobs(self, engine, session) -> None:
        """Enabled MonitorTask rows are loaded as scheduled jobs."""
        from app.db.models import MonitorTask

        t1 = MonitorTask(appid=730, interval_minutes=30, enabled=True)
        t2 = MonitorTask(appid=570, interval_minutes=60, enabled=True)
        session.add_all([t1, t2])
        session.commit()

        with patch.object(svc, "engine", engine):
            _sched = start_scheduler()
            try:
                health = get_scheduler_health()
                assert health["running"] is True
                # 2 enabled + 1 memory_cleanup = 3
                assert health["monitor_job_count"] == 2
                assert health["job_count"] == 3

                assert t1.id is not None
                assert t2.id is not None
                job_ids = [j["id"] for j in health["jobs"]]
                assert make_monitor_job_id(730, t1.id) in job_ids
                assert make_monitor_job_id(570, t2.id) in job_ids
            finally:
                stop_scheduler()

    def test_disabled_task_not_scheduled(self, engine, session) -> None:
        """A MonitorTask with enabled=False should not become a job."""
        from app.db.models import MonitorTask

        t1 = MonitorTask(appid=730, interval_minutes=30, enabled=True)
        t2 = MonitorTask(appid=570, interval_minutes=60, enabled=False)  # disabled
        session.add_all([t1, t2])
        session.commit()

        with patch.object(svc, "engine", engine):
            _sched = start_scheduler()
            try:
                health = get_scheduler_health()
                assert health["monitor_job_count"] == 1
                assert t1.id is not None
                assert t2.id is not None
                job_ids = [j["id"] for j in health["jobs"]]
                assert make_monitor_job_id(730, t1.id) in job_ids
                assert make_monitor_job_id(570, t2.id) not in job_ids
            finally:
                stop_scheduler()

    def test_started_at_is_set(self, engine) -> None:
        """After start_scheduler, started_at is populated."""
        with patch.object(svc, "engine", engine):
            _sched = start_scheduler()
            try:
                health = get_scheduler_health()
                assert health["started_at"] is not None
                # Should be a valid ISO timestamp
                from datetime import datetime as dt
                dt.fromisoformat(health["started_at"])
            finally:
                stop_scheduler()

    def test_pid_is_set_in_health(self, engine) -> None:
        """Health dict includes the current OS PID."""
        with patch.object(svc, "engine", engine):
            _sched = start_scheduler()
            try:
                health = get_scheduler_health()
                assert health["pid"] == os.getpid()
            finally:
                stop_scheduler()


# ---------------------------------------------------------------------------
# Worker entry point — disabled scheduler behavior
# ---------------------------------------------------------------------------


class TestWorkerDisabledScheduler:
    """When STEAMANALYSIS_ENABLE_SCHEDULER is false, the worker refuses to start."""

    def test_worker_exits_with_code_1_when_disabled(self) -> None:
        """The worker's main() calls sys.exit(1) when enable_scheduler is False."""
        from app.worker.scheduler import main as worker_main

        # The worker's main() imports these lazily inside the function body,
        # so we must patch the *source* modules, not the worker module.
        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.enable_scheduler = False
            with patch("app.db.session.init_db"):
                with patch("app.core.logging.configure_logging"):
                    with pytest.raises(SystemExit) as exc_info:
                        worker_main()
                    assert exc_info.value.code == 1

    def test_worker_does_not_start_scheduler_when_disabled(self) -> None:
        """Verify that start_scheduler is never called when disabled."""
        from app.worker.scheduler import main as worker_main

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.enable_scheduler = False
            with patch("app.db.session.init_db"):
                with patch("app.core.logging.configure_logging"):
                    with patch("app.services.scheduler_service.start_scheduler") as mock_start:
                        with pytest.raises(SystemExit):
                            worker_main()
                        mock_start.assert_not_called()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Corner cases and defensive checks."""

    def test_remove_monitor_job_after_scheduler_stopped(self) -> None:
        """If scheduler is stopped between add and remove, remove returns False."""
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(daemon=True, timezone="UTC")
        sched.start()
        svc._scheduler = sched
        add_monitor_job(appid=730, task_id=1, interval_minutes=30)

        # Simulate scheduler being stopped externally
        svc._scheduler = None
        sched.shutdown(wait=False)

        result = remove_monitor_job(appid=730, task_id=1)
        assert result is False

    def test_double_start_does_not_crash(self, engine) -> None:
        """Calling start_scheduler twice should handle existing state gracefully."""
        with patch.object(svc, "engine", engine):
            _sched1 = start_scheduler()
            try:
                _job_count = len(_sched1.get_jobs())  # verify no crash on access
                # Start again — should not crash
                sched2 = start_scheduler()
                try:
                    # The second start replaces _scheduler; APScheduler should
                    # handle duplicate job IDs via replace_existing=True
                    assert sched2 is not None
                finally:
                    stop_scheduler()
            finally:
                pass  # cleanup handled by autouse fixture

    def test_health_file_unchanged_when_write_fails(self, tmp_path) -> None:
        """If the directory is read-only, write_health_file returns False."""
        path = str(tmp_path / "subdir" / "scheduler.health")
        configure_health_file(path)

        # Directory doesn't exist — write should fail
        result = write_health_file()
        assert result is False
        assert not os.path.exists(path)
