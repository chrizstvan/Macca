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

    async def assignment_quota_total(self, mission_id: UUID) -> float:
        """Sum of assigned quota_kg for a mission (null/0 treated as 0)."""

    async def total_assigned_quota(self) -> float:
        """Sum of quota_kg across every assignment (null/0 treated as 0)."""

    async def find_active_by_title(self, fragment: str) -> list[Mission]:
        """Active missions whose title matches ``fragment`` (case-insensitive)."""

    async def create(
        self,
        *,
        title: str,
        description: str = "",
        status: str = "active",
        deadline: str | None = None,
    ) -> Mission:
        """Insert a new mission and return it."""

    async def add_assignment(
        self,
        *,
        volunteer_id: UUID,
        mission_id: UUID,
        assigned_area: str,
        quota_kg: float | None = None,
    ) -> None:
        """Insert a volunteer⇄mission assignment row."""

    async def update_reported_kg(
        self, *, volunteer_id: UUID, mission_id: UUID, total_kg: float
    ) -> None:
        """Mirror the volunteer's running total onto volunteer_missions."""
