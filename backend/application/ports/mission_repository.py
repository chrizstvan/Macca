"""Read/write port for missions + the volunteer⇄mission assignment table."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.domain.entities.mission import Mission, MissionAssignment


class MissionRepository(Protocol):
    async def get_active_for(
        self, volunteer_id: UUID
    ) -> tuple[Mission, MissionAssignment] | None:
        """Return the volunteer's active mission + their assignment row."""

    async def list_active(self) -> list[Mission]: ...

    async def list_assignments(
        self, mission_id: UUID
    ) -> list[MissionAssignment]: ...

    async def update_reported_kg(
        self, *, volunteer_id: UUID, mission_id: UUID, total_kg: float
    ) -> None:
        """Mirror the volunteer's running total onto volunteer_missions."""
