"""Score a volunteer's single-letter quiz reply."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from backend.application.ports.active_quiz_repository import (
    ActiveQuiz,
    ActiveQuizRepository,
)
from backend.application.use_cases._plastic_content import QUIZ_POINTS_CORRECT


@dataclass(frozen=True)
class Correct:
    quiz: ActiveQuiz
    points_awarded: int


@dataclass(frozen=True)
class Incorrect:
    quiz: ActiveQuiz


@dataclass(frozen=True)
class NoActiveQuiz:
    pass


QuizAnswerOutcome = Correct | Incorrect | NoActiveQuiz


@dataclass
class HandleQuizAnswer:
    quizzes: ActiveQuizRepository

    async def execute(
        self, *, volunteer_id: UUID, answer: str
    ) -> QuizAnswerOutcome:
        quiz = await self.quizzes.get_current()
        if quiz is None:
            return NoActiveQuiz()

        normalized = (answer or "").strip().upper()[:1]
        is_correct = normalized == quiz.answer.upper()
        points = QUIZ_POINTS_CORRECT if is_correct else 0

        await self.quizzes.record_attempt(
            volunteer_id=volunteer_id,
            quiz_id=quiz.id,
            answer=normalized,
            is_correct=is_correct,
            points_earned=points,
        )
        return Correct(quiz=quiz, points_awarded=points) if is_correct else Incorrect(quiz=quiz)
