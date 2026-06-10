"""Supabase client singleton with typed helper methods for Macca entities."""

import logging
from functools import lru_cache
from typing import Any
from uuid import UUID

from supabase import Client, create_client

from backend.config import config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached Supabase client instance."""
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


class MaccaDB:
    """Thin wrapper around the Supabase client for common Macca DB operations."""

    def __init__(self) -> None:
        self._db = get_supabase_client()

    # ------------------------------------------------------------------ #
    # Missions                                                             #
    # ------------------------------------------------------------------ #

    def get_mission(self, mission_id: UUID) -> dict[str, Any] | None:
        result = self._db.table("missions").select("*").eq("id", str(mission_id)).single().execute()
        return result.data

    def list_active_missions(self) -> list[dict[str, Any]]:
        result = self._db.table("missions").select("*").eq("status", "active").execute()
        return result.data or []

    def upsert_mission(self, mission: dict[str, Any]) -> dict[str, Any]:
        result = self._db.table("missions").upsert(mission).execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------ #
    # Volunteers                                                           #
    # ------------------------------------------------------------------ #

    def get_volunteer_by_telegram_id(self, telegram_id: str) -> dict[str, Any] | None:
        result = (
            self._db.table("volunteers")
            .select("*")
            .eq("telegram_id", telegram_id)
            .single()
            .execute()
        )
        return result.data

    def upsert_volunteer(self, volunteer: dict[str, Any]) -> dict[str, Any]:
        result = self._db.table("volunteers").upsert(volunteer).execute()
        return result.data[0] if result.data else {}

    # ------------------------------------------------------------------ #
    # Progress updates                                                     #
    # ------------------------------------------------------------------ #

    def insert_progress_update(self, update: dict[str, Any]) -> dict[str, Any]:
        result = self._db.table("progress_updates").insert(update).execute()
        return result.data[0] if result.data else {}

    def list_progress_updates(self, mission_id: UUID) -> list[dict[str, Any]]:
        result = (
            self._db.table("progress_updates")
            .select("*")
            .eq("mission_id", str(mission_id))
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    # ------------------------------------------------------------------ #
    # Impact reports                                                       #
    # ------------------------------------------------------------------ #

    def upsert_impact_report(self, report: dict[str, Any]) -> dict[str, Any]:
        result = self._db.table("impact_reports").upsert(report).execute()
        return result.data[0] if result.data else {}

    def get_impact_report(self, mission_id: UUID) -> dict[str, Any] | None:
        result = (
            self._db.table("impact_reports")
            .select("*")
            .eq("mission_id", str(mission_id))
            .single()
            .execute()
        )
        return result.data
