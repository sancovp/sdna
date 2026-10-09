"""
Scheduler - Runs selfbots on schedule.

Infrastructure layer: implements scheduling logic.
"""

import time
import logging
import threading
from datetime import datetime
from typing import Optional, Callable

from ..domain.models import Selfbot, Schedule

logger = logging.getLogger(__name__)


class SimpleScheduler:
    """
    Simple in-process scheduler for selfbots.

    For production, use system cron or a proper scheduler like APScheduler.
    This is good for development and simple use cases.
    """

    def __init__(self, run_callback: Callable[[Selfbot], None]):
        """
        Args:
            run_callback: Function to call when a selfbot should run.
                          Typically SelfbotRunner.run
        """
        self.run_callback = run_callback
        self._jobs: dict[str, dict] = {}  # selfbot_id -> job info
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def add(self, selfbot: Selfbot) -> None:
        """Add a selfbot to the scheduler."""
        if selfbot.schedule.run_once:
            # Run immediately, don't schedule
            logger.info(f"Running one-shot selfbot: {selfbot.name}")
            self.run_callback(selfbot)
            return

        self._jobs[selfbot.id] = {
            "selfbot": selfbot,
            "last_run": None,
            "next_run": self._calculate_next_run(selfbot.schedule),
        }
        logger.info(f"Scheduled selfbot: {selfbot.name}")

    def remove(self, selfbot_id: str) -> bool:
        """Remove a selfbot from the scheduler."""
        if selfbot_id in self._jobs:
            del self._jobs[selfbot_id]
            return True
        return False

    def _calculate_next_run(self, schedule: Schedule, last_run: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate when the next run should happen."""
        now = datetime.now()

        if schedule.interval_seconds:
            if last_run:
                return datetime.fromtimestamp(
                    last_run.timestamp() + schedule.interval_seconds
                )
            return now  # Run immediately first time

        if schedule.cron_expr:
            # For proper cron parsing, use croniter library
            # This is a simplified placeholder
            logger.warning("Cron expressions require croniter library")
            return None

        return None

    def _tick(self):
        """Check all jobs and run any that are due."""
        now = datetime.now()

        for job_id, job in list(self._jobs.items()):
            next_run = job.get("next_run")
            if next_run and now >= next_run:
                selfbot = job["selfbot"]
                logger.info(f"Scheduler triggering: {selfbot.name}")

                try:
                    self.run_callback(selfbot)
                except Exception as e:
                    logger.exception(f"Scheduled run failed: {selfbot.name}")

                # Update next run time
                job["last_run"] = now
                job["next_run"] = self._calculate_next_run(
                    selfbot.schedule, last_run=now
                )

    def start(self, check_interval: float = 1.0):
        """Start the scheduler in a background thread."""
        if self._running:
            return

        self._running = True

        def run_loop():
            while self._running:
                self._tick()
                time.sleep(check_interval)

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduler stopped")

    def run_blocking(self, check_interval: float = 1.0):
        """Run the scheduler in the main thread (blocking)."""
        self._running = True
        logger.info("Scheduler running (blocking)")
        try:
            while self._running:
                self._tick()
                time.sleep(check_interval)
        except KeyboardInterrupt:
            logger.info("Scheduler interrupted")
        finally:
            self._running = False
