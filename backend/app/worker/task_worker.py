"""Standalone task queue worker entry point.

Usage::

    python -m app.worker.task_worker

Picks up ``pending`` BackgroundTasks and executes them.
This process does **not** serve HTTP.
"""

from __future__ import annotations

import asyncio
import logging
import signal

logger = logging.getLogger("steamanalysis.worker.task_worker")


def main() -> None:
    """Start the background task worker and block until shutdown."""
    from app.core.logging import configure_logging
    from app.db.session import SessionLocal, init_db

    configure_logging()
    logger.info("Starting standalone task worker process")

    # Ensure DB is migrated
    init_db()

    from app.services.task_queue import run_worker, stop_worker

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    worker_task = loop.create_task(run_worker(SessionLocal, poll_interval_s=2.0))

    def _shutdown():
        logger.info("Shutting down task worker...")
        stop_worker()
        worker_task.cancel()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            # Windows: add_signal_handler not supported
            signal.signal(sig, lambda s, f: _shutdown())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        _shutdown()
    finally:
        loop.close()
        logger.info("Task worker stopped")


if __name__ == "__main__":
    main()
