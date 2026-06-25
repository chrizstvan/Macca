"""Team-aggregate port.

Treats ``volunteers.team`` as the team identifier. The repository is
read-only: there's no ``Team`` entity to mutate — the dashboard / SQL is
the source of truth for membership. Use cases ask for rollups (active
member count, summed quota, summed reported kg) when they need to
present team-level progress instead of individual progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class TeamProgress:
    """Snapshot of a team's standing on a specific mission."""

    team: str
    member_count: int
    total_quota_kg: float
    reported_kg: float

    @property
    def pct(self) -> float:
        if self.total_quota_kg <= 0:
            return 0.0
        return round(self.reported_kg / self.total_quota_kg * 100, 1)

    @property
    def remaining_kg(self) -> float:
        return max(self.total_quota_kg - self.reported_kg, 0.0)


class TeamRepository(Protocol):
    async def get_progress(
        self, *, team: str, mission_id: UUID
    ) -> TeamProgress: ...

    async def list_member_names(self, *, team: str) -> list[str]: ...
