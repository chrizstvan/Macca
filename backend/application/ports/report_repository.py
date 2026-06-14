"""Read/write port for the reports aggregate."""

from __future__ import annotations

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
