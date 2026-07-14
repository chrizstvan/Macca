"""Broadcast an explicit quiz spec to volunteers right now.

Generalises :class:`SendWeeklyQuiz` (which uses a hardcoded weekly spec) to an
arbitrary, fasilitator-approved quiz. Creates the ``active_quizzes`` row so
:class:`HandleQuizAnswer` can score replies, then broadcasts to all active
volunteers. Used by both the immediate-send approval path and the scheduled
``scheduled_messages`` quiz dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.application.ports.active_quiz_repository import (
    ActiveQuiz,
    ActiveQuizRepository,
)
from backend.application.ports.notifier import Notifier
from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.application.use_cases._plastic_content import (
    QUIZ_TTL_HOURS,
    format_quiz_message,
)


@dataclass(frozen=True)
class QuizBroadcast:
    quiz: ActiveQuiz
    recipients_dispatched: int


@dataclass
class BroadcastQuizNow:
    volunteers: VolunteerRepository
    quizzes: ActiveQuizRepository
    notifier: Notifier

    async def execute(self, spec: dict) -> QuizBroadcast:
        quiz = await self.quizzes.create(
            question=spec["question"],
            options=list(spec.get("options") or []),
            answer=spec["answer"],
            explanation=spec.get("explanation", ""),
            ttl_hours=QUIZ_TTL_HOURS,
        )
        fallback_text = format_quiz_message(spec)
        recipients = await self.volunteers.list_active()
        dispatched = await self.notifier.broadcast_quiz(
            recipients, dict(spec), fallback_text
        )
        return QuizBroadcast(quiz=quiz, recipients_dispatched=dispatched)
