"""APScheduler-backed task scheduler for periodic Macca jobs."""

import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class MaccaScheduler:
    """Thin wrapper around APScheduler's AsyncIOScheduler.

    Provides named helpers for the recurring jobs Macca needs (daily impact
    summaries, hourly escalation checks, etc.) and a generic interface for
    registering arbitrary coroutines on cron or interval triggers.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.start()
        logger.info("Macca scheduler started")

    def shutdown(self, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)
        logger.info("Macca scheduler stopped")

    def add_interval_job(
        self,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        job_id: str | None = None,
    ) -> str:
        """Register a coroutine to run on a fixed interval."""
        job = self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours),
            id=job_id,
            replace_existing=True,
        )
        logger.info("Scheduled interval job '%s' every %sh%sm%ss", job.id, hours, minutes, seconds)
        return job.id

    def add_cron_job(
        self,
        func: Callable,
        cron_expression: str,
        job_id: str | None = None,
    ) -> str:
        """Register a coroutine to run on a cron schedule (e.g. '0 9 * * *')."""
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError(f"Expected 5-part cron expression, got: {cron_expression!r}")

        minute, hour, day, month, day_of_week = parts
        job = self._scheduler.add_job(
            func,
            trigger=CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            ),
            id=job_id,
            replace_existing=True,
        )
        logger.info("Scheduled cron job '%s' at '%s'", job.id, cron_expression)
        return job.id

    def remove_job(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)
        logger.info("Removed scheduled job '%s'", job_id)
