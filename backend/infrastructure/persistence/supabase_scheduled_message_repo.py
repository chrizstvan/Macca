"""Supabase-backed ScheduledMessageRepository (the ``scheduled_messages`` queue)."""

from __future__ import annotations

from datetime import datetime

from supabase import Client

from backend.application.ports.scheduled_message_repository import (
    ScheduledMessageRepository,
)


class SupabaseScheduledMessageRepository(ScheduledMessageRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def schedule_reminder(
        self,
        *,
        message_template: str,
        recipient_filter: str,
        action_item_id: str | None,
        scheduled_at: datetime,
        created_by: str,
    ) -> None:
        self._db.table("scheduled_messages").insert(
            {
                "message_template": message_template,
                "recipient_filter": recipient_filter,
                "action_item_id": action_item_id,
                "scheduled_at": scheduled_at.isoformat(),
                "status": "pending",
                "created_by": created_by,
            }
        ).execute()

    async def schedule_quiz(
        self,
        *,
        quiz: dict,
        recipient_filter: str,
        quiz_id: str | None,
        scheduled_at: datetime,
        created_by: str,
    ) -> None:
        self._db.table("scheduled_messages").insert(
            {
                "quiz": quiz,
                "recipient_filter": recipient_filter,
                "quiz_id": quiz_id,
                "scheduled_at": scheduled_at.isoformat(),
                "status": "pending",
                "created_by": created_by,
            }
        ).execute()

    async def list_due(self, now: datetime) -> list[dict]:
        return (
            self._db.table("scheduled_messages")
            .select("*")
            .eq("status", "pending")
            .lte("scheduled_at", now.isoformat())
            .execute()
            .data
            or []
        )

    async def mark(self, message_id: str, status: str) -> None:
        self._db.table("scheduled_messages").update({"status": status}).eq(
            "id", message_id
        ).execute()
