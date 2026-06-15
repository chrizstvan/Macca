"""SchedulerManager — APScheduler wrapper for Macca's recurring jobs.

Features:

* ``AsyncIOScheduler`` running on the FastAPI event loop.
* Timezone fixed to ``Asia/Jakarta`` so cron literals match real WIB time
  regardless of where the host runs.
* Default ``MemoryJobStore`` — fast, zero-dep, fine for the single-uvicorn
  deploy. The 4 default crons are re-registered on every boot via
  ``register_default_jobs()`` so disk persistence isn't required for them.
  Swap to ``RedisJobStore`` (or any APScheduler-supported jobstore) when
  horizontal scaling is needed — pass ``jobstores=`` to the underlying
  scheduler instead of relying on the in-memory default.
* Listener attached so every fired job is logged with elapsed time and
  any exception is captured without taking the scheduler down.
* ``register_default_jobs`` wires up the four Phase-7 program jobs in one
  call — main.py just calls ``manager.start(default_jobs=True)``.

The four default jobs:

* ``daily_reminder``     — 18:00 WIB — DM volunteers with active mission,
                           less than 2 days to deadline, no report today.
* ``morning_briefing``   — 07:00 WIB — DM fasilitator the morning summary.
* ``daily_content``      — 20:00 WIB — generate Instagram caption when
                           there were reports today.
* ``weekly_report``      — Mon 08:00 WIB — fasilitator weekly report.

Older callers used ``MaccaScheduler``; an alias is kept so they don't
break during the transition.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


# --------------------------------------------------------------------------- #
# Default job bodies                                                           #
# --------------------------------------------------------------------------- #


async def _daily_reminder_job() -> None:
    """Send a progress nudge to volunteers near their mission deadline."""
    from backend.agents.services.notifications import notify_volunteer
    from backend.database.supabase_client import db

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_iso = today_start.isoformat()

    assignments = (
        db.table("volunteer_missions")
        .select(
            "quota_kg, reported_kg, assigned_area, "
            "volunteers(id, name, phone, telegram_id), "
            "missions(id, title, deadline, status)"
        )
        .execute()
        .data
        or []
    )

    dispatched = 0
    for assignment in assignments:
        mission = assignment.get("missions") or {}
        volunteer = assignment.get("volunteers") or {}
        if mission.get("status") != "active":
            continue

        deadline_raw = mission.get("deadline")
        if not deadline_raw:
            continue
        try:
            deadline_dt = datetime.fromisoformat(
                str(deadline_raw).replace("Z", "+00:00")
            )
        except ValueError:
            continue

        # Skip when more than 2 days remain or already overdue.
        delta = deadline_dt - now
        if delta < timedelta(days=0) or delta > timedelta(days=2):
            continue

        # Skip when the volunteer already reported today on this mission.
        reported_today = (
            db.table("reports")
            .select("id")
            .eq("volunteer_id", volunteer.get("id"))
            .eq("mission_id", mission.get("id"))
            .gte("reported_at", today_iso)
            .limit(1)
            .execute()
            .data
            or []
        )
        if reported_today:
            continue

        quota = float(assignment.get("quota_kg") or 0)
        reported_kg = float(assignment.get("reported_kg") or 0)
        days_left = max(delta.days, 0)
        text = (
            f"Hei {volunteer.get('name') or 'Volunteer'}! 💪 Reminder: "
            f"deadline laporan {days_left} hari lagi. Progress kamu "
            f"{reported_kg:g}/{quota:g} kg. Semangat!"
        )
        try:
            await notify_volunteer(volunteer, text)
            dispatched += 1
        except Exception as exc:
            logger.warning(
                "daily_reminder send failed for %s: %s",
                volunteer.get("name"), exc,
            )

    logger.info("daily_reminder dispatched to %d volunteer(s)", dispatched)


async def _morning_briefing_job() -> None:
    from backend.agents.fasilitator_hub import FasilitatorHubAgent

    await FasilitatorHubAgent().get_morning_briefing()


async def _daily_content_job() -> None:
    """Only run when at least one report landed today."""
    from backend.agents.content_creator import ContentCreatorAgent
    from backend.database.supabase_client import db

    today_iso = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    has_today = (
        db.table("reports")
        .select("id")
        .gte("reported_at", today_iso)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not has_today:
        logger.info("daily_content: no reports today, skipping")
        return
    await ContentCreatorAgent().daily_content_summary()


async def _weekly_report_job() -> None:
    from backend.agents.impact_analyzer import ImpactAnalyzerAgent

    await ImpactAnalyzerAgent().weekly_report()


DEFAULT_JOBS: tuple[dict, ...] = (
    {
        "id": "daily_reminder",
        "func": _daily_reminder_job,
        "cron": "0 18 * * *",  # 18:00 WIB
    },
    {
        "id": "morning_briefing",
        "func": _morning_briefing_job,
        "cron": "0 7 * * *",  # 07:00 WIB
    },
    {
        "id": "daily_content",
        "func": _daily_content_job,
        "cron": "0 20 * * *",  # 20:00 WIB
    },
    {
        "id": "weekly_report",
        "func": _weekly_report_job,
        "cron": "0 8 * * 1",  # Mon 08:00 WIB
    },
)


# --------------------------------------------------------------------------- #
# SchedulerManager                                                             #
# --------------------------------------------------------------------------- #


class SchedulerManager:
    """Persistent APScheduler wrapper running on the asyncio loop."""

    def __init__(
        self,
        *,
        timezone: ZoneInfo = JAKARTA_TZ,
    ) -> None:
        # AsyncIOScheduler defaults to MemoryJobStore — explicit kwargs would
        # only be needed when swapping to Redis (horizontal scale) or another
        # store. Jobs are ephemeral; defaults re-register on boot via
        # register_default_jobs().
        self._scheduler = AsyncIOScheduler(timezone=timezone)
        self._scheduler.add_listener(
            self._on_job_event,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self, *, default_jobs: bool = False) -> None:
        if default_jobs:
            self.register_default_jobs()
        self._scheduler.start()
        logger.info(
            "SchedulerManager started — %d job(s) registered",
            len(self._scheduler.get_jobs()),
        )

    def shutdown(self, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)
        logger.info("SchedulerManager stopped")

    # ------------------------------------------------------------------ #
    # Job registration                                                    #
    # ------------------------------------------------------------------ #

    def add_interval_job(
        self,
        func: Callable[..., Awaitable],
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        job_id: str | None = None,
    ) -> str:
        job = self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(
                seconds=seconds, minutes=minutes, hours=hours
            ),
            id=job_id,
            replace_existing=True,
        )
        logger.info(
            "Scheduled interval job '%s' every %sh%sm%ss",
            job.id, hours, minutes, seconds,
        )
        return job.id

    def add_cron_job(
        self,
        func: Callable[..., Awaitable],
        cron_expression: str,
        job_id: str | None = None,
    ) -> str:
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError(
                f"Expected 5-part cron expression, got: {cron_expression!r}"
            )
        minute, hour, day, month, day_of_week = parts
        job = self._scheduler.add_job(
            func,
            trigger=CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=self._scheduler.timezone,
            ),
            id=job_id,
            replace_existing=True,
        )
        logger.info("Scheduled cron job '%s' at '%s'", job.id, cron_expression)
        return job.id

    def remove_job(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)
        logger.info("Removed scheduled job '%s'", job_id)

    def register_default_jobs(self) -> None:
        """Wire the four Macca recurring jobs in a single call."""
        for spec in DEFAULT_JOBS:
            self.add_cron_job(spec["func"], spec["cron"], job_id=spec["id"])

    # ------------------------------------------------------------------ #
    # Listener                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _on_job_event(event) -> None:
        when = datetime.now(JAKARTA_TZ).isoformat(timespec="seconds")
        if getattr(event, "exception", None):
            logger.error(
                "[%s] job %s FAILED — %s",
                when, event.job_id, event.exception,
            )
        else:
            logger.info("[%s] job %s executed", when, event.job_id)


# Back-compat alias for older imports.
MaccaScheduler = SchedulerManager
