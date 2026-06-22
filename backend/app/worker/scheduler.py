"""Standalone scheduler entry point.

Usage::

    python -m app.worker.scheduler
    STEAMANALYSIS_ENABLE_SCHEDULER=true python -m app.worker.scheduler

Runs the APScheduler in the foreground (blocking) so Docker / process
managers can supervise it directly.  This process does **not** serve HTTP.

**Health file**: On startup the worker writes a JSON health file to the
directory specified by ``STEAMANALYSIS_SCHEDULER_HEALTH_FILE`` (defaults to
``/tmp/steamanalysis-scheduler.health``).  The file is updated every 30
seconds and removed on clean shutdown.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

logger = logging.getLogger("steamanalysis.worker.scheduler")

# Default health file path — override with env var
HEALTH_FILE_DEFAULT = os.environ.get(
    "STEAMANALYSIS_SCHEDULER_HEALTH_FILE",
    "/tmp/steamanalysis-scheduler.health",
)


def main() -> None:
    """Start the scheduler and block until a shutdown signal is received."""
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.session import init_db

    configure_logging()
    logger.info("Starting standalone scheduler process (pid=%d)", os.getpid())

    # Ensure DB is migrated before any scheduled jobs run
    init_db()

    settings = get_settings()
    if not settings.enable_scheduler:
        logger.error(
            "STEAMANALYSIS_ENABLE_SCHEDULER is not true — refusing to start scheduler."
        )
        sys.exit(1)

    from app.services.scheduler_service import (
        configure_health_file,
        start_scheduler,
        stop_scheduler,
        write_health_file,
    )

    # Configure the health file so the service writes state snapshots
    configure_health_file(HEALTH_FILE_DEFAULT)
    logger.info("scheduler health file path: %s", HEALTH_FILE_DEFAULT)

    _scheduler_ref = start_scheduler()
    logger.info("Scheduler started (pid=%d), waiting for shutdown signal...", os.getpid())

    # Periodic heartbeat: update the health file so external monitors know
    # the process is still alive (the file mtime doubles as a liveness probe).
    HEARTBEAT_INTERVAL = 30  # seconds

    def _heartbeat() -> None:
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            try:
                write_health_file()
            except Exception:
                logger.debug("heartbeat write skipped", exc_info=True)

    import threading
    heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True, name="scheduler-heartbeat")
    heartbeat_thread.start()

    # Block until SIGINT or SIGTERM
    def _shutdown(signum, frame):
        logger.info("Received signal %s, shutting down scheduler...", signum)
        stop_scheduler()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Keep the main thread alive
    try:
        signal.pause()  # type: ignore[attr-defined]  # not available on Windows, fallback below
    except AttributeError:
        # Windows doesn't have signal.pause()
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
