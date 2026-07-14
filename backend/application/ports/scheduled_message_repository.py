"""Read/write port for the ``scheduled_messages`` dispatch queue.

Rows are drained every minute by the scheduler job: reminder rows broadcast a
templated text, quiz rows broadcast a quiz (and create the live
``active_quizzes`` row). Keeps the presentation layer (fasilitator-hub mixins)
and the scheduler job off direct ``db.table(...)`` calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class ScheduledMessageRepository(Protocol):
    async def schedule_reminder(
        self,
        *,
        message_template: str,
        recipient_filter: str,
        action_item_id: str | None,
        scheduled_at: datetime,
        created_by: str,
    ) -> None:
        """Queue a reminder broadcast for ``scheduled_at``."""

    async def schedule_quiz(
        self,
        *,
        quiz: dict,
        recipient_filter: str,
        quiz_id: str | None,
        scheduled_at: datetime,
        created_by: str,
    ) -> None:
        """Queue a quiz broadcast for ``scheduled_at``."""

    async def list_due(self, now: datetime) -> list[dict]:
        """Pending rows whose ``scheduled_at`` has passed (as raw dict rows)."""

    async def mark(self, message_id: str, status: str) -> None:
        """Set a row's lifecycle ``status`` (sent / failed / cancelled)."""
