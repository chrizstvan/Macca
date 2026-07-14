"""Read/write port for the ``quizzes`` draft table.

Holds fasilitator-reviewed quiz drafts through their lifecycle
``draft → approved → sent`` (or ``cancelled``). Distinct from
``active_quizzes`` (the live, answerable quiz that feeds ranking): a quiz
becomes an ``active_quizzes`` row only at send time, after approval.
"""

from __future__ import annotations

from typing import Protocol


class QuizDraftRepository(Protocol):
    async def create_draft(
        self,
        *,
        question: str,
        options: list[str],
        answer: str,
        explanation: str,
    ) -> str:
        """Insert a ``status='draft'`` quiz; return its id."""

    async def get_latest_draft(self) -> dict | None:
        """Most recent ``status='draft'`` row, or None."""

    async def update(self, quiz_id: str, fields: dict) -> None:
        """Patch arbitrary columns on a quiz row."""

    async def update_status(self, quiz_id: str, status: str) -> None:
        """Set the lifecycle ``status`` (approved / sent / cancelled)."""
