"""Supabase-backed ContentDraftRepository (the ``content_drafts`` table)."""

from __future__ import annotations

from supabase import Client

from backend.application.ports.content_draft_repository import (
    ContentDraftRepository,
)


class SupabaseContentDraftRepository(ContentDraftRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def create_draft(
        self, *, type: str, topic: str, content: str
    ) -> str:
        row = (
            self._db.table("content_drafts")
            .insert({"type": type, "topic": topic, "content": content})
            .execute()
            .data[0]
        )
        return row["id"]

    async def get_latest_draft(self, type: str) -> dict | None:
        rows = (
            self._db.table("content_drafts")
            .select("*")
            .eq("type", type)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def update(self, draft_id: str, fields: dict) -> None:
        self._db.table("content_drafts").update(fields).eq(
            "id", draft_id
        ).execute()
