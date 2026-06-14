"""Job 4 — weekly quiz broadcast.

Stores the quiz row in ``active_quizzes`` so :class:`HandleQuizAnswer`
can score later replies. TTL defaults to 24 hours.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.application.ports.active_quiz_repository import (
    ActiveQuiz,
    ActiveQuizRepository,
)
from backend.application.ports.clock import Clock
from backend.application.ports.notifier import Notifier
from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.application.use_cases._plastic_content import (
    QUIZ_TTL_HOURS,
    format_quiz_message,
    quiz_for,
)


@dataclass(frozen=True)
class QuizSent:
    quiz: ActiveQuiz
    recipients_dispatched: int


@dataclass
class SendWeeklyQuiz:
    volunteers: VolunteerRepository
    quizzes: ActiveQuizRepository
    notifier: Notifier
    clock: Clock

    async def execute(self) -> QuizSent:
        iso_week = self.clock.today().isocalendar()[1]
        spec = quiz_for(iso_week)
        quiz = await self.quizzes.create(
            question=spec["question"],
            options=list(spec["options"]),
            answer=spec["answer"],
            explanation=spec["explanation"],
            ttl_hours=QUIZ_TTL_HOURS,
        )
        message = format_quiz_message(spec)
        recipients = await self.volunteers.list_active()
        dispatched = await self.notifier.broadcast(recipients, message)
        return QuizSent(quiz=quiz, recipients_dispatched=dispatched)
