"""Job 1 — weekly plastic-fact broadcast."""

from __future__ import annotations

from dataclasses import dataclass

from backend.application.ports.clock import Clock
from backend.application.ports.notifier import Notifier
from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.application.use_cases._plastic_content import (
    format_weekly_fact_message,
)


@dataclass
class SendWeeklyPlasticFact:
    volunteers: VolunteerRepository
    notifier: Notifier
    clock: Clock

    async def execute(self) -> int:
        """Send the week's fact to every active volunteer. Returns count."""
        iso_week = self.clock.today().isocalendar()[1]
        message = format_weekly_fact_message(iso_week)
        recipients = await self.volunteers.list_active()
        return await self.notifier.broadcast(recipients, message)
