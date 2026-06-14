"""Read/write port for the weekly active quiz."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ActiveQuiz:
    id: UUID
    question: str
    options: list[str]
    answer: str          # canonical uppercase letter
    explanation: str
    expires_at: datetime


class ActiveQuizRepository(Protocol):
    async def create(
        self,
        *,
        question: str,
        options: list[str],
        answer: str,
        explanation: str,
        ttl_hours: int,
    ) -> ActiveQuiz: ...

    async def get_current(self) -> ActiveQuiz | None:
        """Return the most recent non-expired quiz, or None."""

    async def record_attempt(
        self,
        *,
        volunteer_id: UUID,
        quiz_id: UUID,
        answer: str,
        is_correct: bool,
        points_earned: int,
    ) -> None: ...
