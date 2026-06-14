"""Job 2 — pre-mission field-guide broadcast."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from backend.application.ports.notifier import Notifier
from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.application.use_cases._plastic_content import (
    MISSION_EDUCATION_BRIEF,
)


@dataclass
class SendMissionEducationBrief:
    volunteers: VolunteerRepository
    notifier: Notifier

    async def execute(self, *, mission_id: UUID) -> int:
        recipients = await self.volunteers.list_for_mission(mission_id)
        return await self.notifier.broadcast(recipients, MISSION_EDUCATION_BRIEF)
