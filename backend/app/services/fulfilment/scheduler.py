"""Fulfilment recovery background scheduler for asyncio-based periodic execution."""

import asyncio
import logging
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.fulfilment.recovery import (
    FulfilmentRecoveryResult,
    FulfilmentRecoveryWorker,
)

logger = logging.getLogger("shopeasy.fulfilment.scheduler")


class FulfilmentRecoveryScheduler:
    """Asyncio background task scheduler for recurring fulfilment recovery sweeps.

    Design Principles:
    - Minimal & Safe: Uses standard asyncio background task (`asyncio.create_task`).
    - Non-blocking: Runs in the asyncio event loop without blocking FastAPI request handling or startup.
    - Single Instance Guard: Uses an internal lock and state flag (`is_running`) to prevent duplicate schedulers.
      Note: This guard is process-local. On multi-worker web deployments (e.g. Uvicorn --workers > 1),
      FULFILMENT_RECOVERY_ENABLED=False must remain the default. Production deployments should use an
      external Render Cron Job running `python -m app.services.fulfilment.recovery`.
    - Graceful Shutdown: `stop()` cancels the task and waits for the in-flight loop to exit cleanly.
    - Configurable: Interval and batch size are controlled by `settings.FULFILMENT_RECOVERY_INTERVAL_SECONDS`
      and `settings.FULFILMENT_RECOVERY_BATCH_SIZE`.
    - Conservative Default: Only starts if `settings.FULFILMENT_RECOVERY_ENABLED` is True.
    """

    def __init__(
        self,
        interval_seconds: Optional[int] = None,
        batch_size: Optional[int] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ):
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._session_factory = session_factory
        self._task: Optional[asyncio.Task] = None
        self._is_running = False
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._is_running and self._task is not None and not self._task.done()

    @property
    def interval_seconds(self) -> int:
        return self._interval_seconds or settings.FULFILMENT_RECOVERY_INTERVAL_SECONDS

    @property
    def batch_size(self) -> int:
        return self._batch_size or settings.FULFILMENT_RECOVERY_BATCH_SIZE

    async def _loop(self) -> None:
        """Continuous recovery loop sleeping for `interval_seconds` between sweeps."""
        logger.info(
            f"Fulfilment recovery scheduler started (interval={self.interval_seconds}s, batch_size={self.batch_size})."
        )
        while not self._stop_event.is_set():
            try:
                # Run the recovery sweep synchronously in default thread pool to avoid blocking async loop
                loop = asyncio.get_running_loop()
                result: FulfilmentRecoveryResult = await loop.run_in_executor(
                    None,
                    FulfilmentRecoveryWorker.run_sweep,
                    None,  # db
                    self._session_factory,
                    self.batch_size,
                )
                if result.candidates_found > 0:
                    logger.info(
                        f"Recovery sweep completed: {result.orders_fulfilled} fulfilled, "
                        f"{result.orders_already_fulfilled} already fulfilled, {result.orders_failed} failed."
                    )
            except asyncio.CancelledError:
                logger.info("Fulfilment recovery scheduler received cancellation.")
                break
            except Exception as exc:
                logger.error(f"Unexpected error during fulfilment recovery sweep: {exc}", exc_info=True)

            try:
                # Wait for interval or stop event
                await asyncio.wait_for(self._stop_event.wait(), timeout=float(self.interval_seconds))
            except asyncio.TimeoutError:
                pass  # Timeout means interval elapsed, run next sweep
            except asyncio.CancelledError:
                break

        self._is_running = False
        logger.info("Fulfilment recovery scheduler stopped.")

    def start(self) -> bool:
        """Start the background scheduler task if enabled and not already running."""
        if not settings.FULFILMENT_RECOVERY_ENABLED:
            logger.info("Fulfilment recovery scheduler is disabled by configuration (FULFILMENT_RECOVERY_ENABLED=False).")
            return False

        if self.is_running:
            logger.warning("Fulfilment recovery scheduler is already running; skipping start.")
            return False

        self._stop_event.clear()
        self._is_running = True
        self._task = asyncio.create_task(self._loop(), name="fulfilment_recovery_scheduler")
        return True

    async def stop(self) -> None:
        """Gracefully stop the background scheduler task."""
        if not self._is_running and (self._task is None or self._task.done()):
            return

        logger.info("Stopping fulfilment recovery scheduler...")
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._is_running = False
        self._task = None
        logger.info("Fulfilment recovery scheduler shutdown complete.")


# Global singleton instance
recovery_scheduler = FulfilmentRecoveryScheduler()
