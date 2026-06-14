"""Mission + per-volunteer mission assignment entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from backend.domain.value_objects.kg import Kg


@dataclass
class Mission:
    id: UUID
    title: str
    description: str | None
    status: str
    deadline: date | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def days_until_deadline(self, today: date) -> int | None:
        if self.deadline is None:
            return None
        return (self.deadline - today).days


@dataclass
class MissionAssignment:
    """Pairs a volunteer with a mission and the agreed quota/area."""

    volunteer_id: UUID
    mission_id: UUID
    quota_kg: Kg
    assigned_area: str
    reported_kg: Kg | None = None

    def remaining_kg(self) -> float:
        """How many kg are still owed against the quota (0 when complete)."""
        done = self.reported_kg.value if self.reported_kg is not None else 0.0
        return max(self.quota_kg.value - done, 0.0)

    def percent_complete(self) -> float:
        if self.quota_kg.value <= 0:
            return 0.0
        done = self.reported_kg.value if self.reported_kg is not None else 0.0
        return (done / self.quota_kg.value) * 100
