"""Per-volunteer impact + quiz score, plus the leaderboard rank."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

IMPACT_WEIGHT = 0.95
QUIZ_WEIGHT = 0.05

MAX_COMPONENT_SCORE = 100.0


def _clamp(value: float) -> float:
    return max(0.0, min(value, MAX_COMPONENT_SCORE))


@dataclass
class Score:
    volunteer_id: UUID
    impact_score: float = 0.0
    quiz_score: float = 0.0
    rank: int | None = None
    prev_rank: int | None = None
    last_updated: datetime | None = None

    def __post_init__(self) -> None:
        self.impact_score = _clamp(self.impact_score)
        self.quiz_score = _clamp(self.quiz_score)

    @property
    def total_score(self) -> float:
        return self.impact_score * IMPACT_WEIGHT + self.quiz_score * QUIZ_WEIGHT

    @property
    def rank_change(self) -> int:
        """Positive = improved, negative = dropped, 0 = unchanged/no data."""
        if self.prev_rank is None or self.rank is None:
            return 0
        return self.prev_rank - self.rank

    def update_rank(self, new_rank: int) -> None:
        self.prev_rank = self.rank
        self.rank = new_rank
