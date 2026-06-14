"""Supabase-backed ActiveQuizRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from supabase import Client

from backend.application.ports.active_quiz_repository import (
    ActiveQuiz,
    ActiveQuizRepository,
)
from backend.utils.date_utils import parse_iso_datetime


def _quiz_from_row(row: dict) -> ActiveQuiz:
    return ActiveQuiz(
        id=UUID(row["id"]),
        question=row["question"],
        options=list(row.get("options") or []),
        answer=row["answer"],
        explanation=row.get("explanation") or "",
        expires_at=parse_iso_datetime(row["expires_at"]) or datetime.now(timezone.utc),
    )


class SupabaseActiveQuizRepository(ActiveQuizRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def create(
        self,
        *,
        question: str,
        options: list[str],
        answer: str,
        explanation: str,
        ttl_hours: int,
    ) -> ActiveQuiz:
        expires = (
            datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        ).isoformat()
        row = (
            self._db.table("active_quizzes")
            .insert(
                {
                    "question": question,
                    "options": options,
                    "answer": answer.upper(),
                    "explanation": explanation,
                    "expires_at": expires,
                }
            )
            .execute()
            .data[0]
        )
        return _quiz_from_row(row)

    async def get_current(self) -> ActiveQuiz | None:
        now = datetime.now(timezone.utc).isoformat()
        rows = (
            self._db.table("active_quizzes")
            .select("*")
            .gte("expires_at", now)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return _quiz_from_row(rows[0]) if rows else None

    async def record_attempt(
        self,
        *,
        volunteer_id: UUID,
        quiz_id: UUID,
        answer: str,
        is_correct: bool,
        points_earned: int,
    ) -> None:
        self._db.table("quiz_attempts").insert(
            {
                "volunteer_id": str(volunteer_id),
                "quiz_id": str(quiz_id),
                "answer": answer.upper(),
                "is_correct": is_correct,
                "points_earned": points_earned,
            }
        ).execute()
