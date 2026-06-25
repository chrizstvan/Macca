"""Supabase-backed FasilitatorContextRepository."""

from __future__ import annotations

from supabase import Client

from backend.application.ports.fasilitator_context_repository import (
    FasilitatorContextRepository,
)


class SupabaseFasilitatorContextRepository(FasilitatorContextRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def get(self, key: str) -> str | None:
        rows = (
            self._db.table("fasilitator_context")
            .select("value")
            .eq("key", key)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0]["value"] if rows else None

    async def upsert(self, key: str, value: str) -> None:
        self._db.table("fasilitator_context").upsert(
            {"key": key, "value": value},
            on_conflict="key",
        ).execute()
