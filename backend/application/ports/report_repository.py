"""Read/write port for the reports aggregate."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.domain.entities.report import Report
from backend.domain.value_objects.kg import Kg


class ReportRepository(Protocol):
    async def insert(self, report: Report) -> Report: ...

    async def update(
        self,
        report_id: UUID,
        *,
        kg: Kg,
        location: str,
        photo_url: str | None = None,
    ) -> None: ...

    async def find_latest_today(
        self, volunteer_id: UUID, mission_id: UUID
    ) -> Report | None: ...

    async def find_similar_today(
        self,
        volunteer_id: UUID,
        mission_id: UUID,
        *,
        kg: Kg,
        tolerance_kg: float = 1.0,
    ) -> Report | None: ...

    async def total_kg_for(
        self, volunteer_id: UUID, mission_id: UUID
    ) -> float: ...

    async def list_for_mission(
        self, mission_id: UUID, *, limit: int | None = None
    ) -> list[Report]: ...

    async def list_for_volunteer_in_mission(
        self, volunteer_id: UUID, mission_id: UUID
    ) -> list[Report]:
        """All of a volunteer's reports for one mission, newest first."""

    async def program_total_kg(self, mission_id: UUID) -> float:
        """Sum of kg for a mission, counting rows where ``verified`` is not False."""

    async def count_reporters_today(self, mission_id: UUID) -> int:
        """Distinct volunteers who reported on this mission since midnight UTC."""

    async def total_kg_for_volunteer(self, volunteer_id: UUID) -> float:
        """Sum of a volunteer's kg across all missions."""

    async def latest_for_volunteer(
        self, volunteer_id: UUID
    ) -> Report | None:
        """The volunteer's most recent report, or None."""

    async def list_for_volunteer(
        self, volunteer_id: UUID, *, limit: int | None = None
    ) -> list[Report]:
        """A volunteer's reports across all missions, newest first."""

    async def list_all(self) -> list[Report]:
        """Every report in the program (used by fasilitator strategy aggregates)."""

    async def list_today(self) -> list[Report]:
        """All reports program-wide since midnight UTC."""

    async def list_between(
        self, start: datetime, end: datetime
    ) -> list[Report]:
        """Reports with ``start <= reported_at < end``."""

    async def count_flagged_unverified(self) -> int:
        """Number of reports with is_flagged=True and verified=False."""

    async def list_flagged_unverified(self) -> list[Report]:
        """Flagged, unverified reports newest first (for the review digest)."""
