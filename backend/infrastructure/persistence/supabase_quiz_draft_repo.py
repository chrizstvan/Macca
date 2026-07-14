"""Supabase-backed QuizDraftRepository (the ``quizzes`` draft table)."""

from __future__ import annotations

from supabase import Client

from backend.application.ports.quiz_draft_repository import QuizDraftRepository


class SupabaseQuizDraftRepository(QuizDraftRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def create_draft(
        self,
        *,
        question: str,
        options: list[str],
        answer: str,
        explanation: str,
    ) -> str:
        row = (
            self._db.table("quizzes")
            .insert(
                {
                    "question": question,
                    "options": options,
                    "answer": (answer or "").upper(),
                    "explanation": explanation,
                    "status": "draft",
                }
            )
            .execute()
            .data[0]
        )
        return row["id"]

    async def get_latest_draft(self) -> dict | None:
        rows = (
            self._db.table("quizzes")
            .select("*")
            .eq("status", "draft")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def update(self, quiz_id: str, fields: dict) -> None:
        self._db.table("quizzes").update(fields).eq("id", quiz_id).execute()

    async def update_status(self, quiz_id: str, status: str) -> None:
        self._db.table("quizzes").update({"status": status}).eq(
            "id", quiz_id
        ).execute()
