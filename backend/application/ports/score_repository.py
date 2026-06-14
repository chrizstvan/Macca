"""Read/write port for the volunteer leaderboard."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.domain.entities.score import Score


class ScoreRepository(Protocol):
    async def get(self, volunteer_id: UUID) -> Score | None: ...

    async def upsert(self, score: Score) -> None: ...

    async def leaderboard(self, *, limit: int = 10) -> list[Score]: ...

    async def total_count(self) -> int: ...
