"""Supabase-backed VolunteerQueryRepository (read-model / query side)."""

from __future__ import annotations

from uuid import UUID

from supabase import Client

from backend.application.ports.volunteer_query_repository import (
    VolunteerQueryRepository,
    VolunteerRow,
)


class SupabaseVolunteerQueryRepository(VolunteerQueryRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def get_by_id(self, volunteer_id: UUID | str) -> VolunteerRow | None:
        rows = (
            self._db.table("volunteers")
            .select("*")
            .eq("id", str(volunteer_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def get_by_telegram_id(
        self, telegram_id: int
    ) -> VolunteerRow | None:
        rows = (
            self._db.table("volunteers")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def get_by_phone(self, phone: str) -> VolunteerRow | None:
        rows = (
            self._db.table("volunteers")
            .select("*")
            .eq("phone", phone)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def list_active(self) -> list[VolunteerRow]:
        return (
            self._db.table("volunteers")
            .select("*")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )

    async def list_by_team(self, team: str) -> list[VolunteerRow]:
        from backend.infrastructure.persistence._mappers import _coerce_team

        target = (team or "").strip().lower()
        return [
            v
            for v in await self.list_active()
            if (_coerce_team(v.get("team")) or "").lower() == target
        ]

    async def list_all(self) -> list[VolunteerRow]:
        return (
            self._db.table("volunteers").select("*").execute().data or []
        )

    async def find_by_name(self, fragment: str) -> list[VolunteerRow]:
        return (
            self._db.table("volunteers")
            .select("*")
            .ilike("name", f"%{fragment}%")
            .execute()
            .data
            or []
        )

    async def names_for(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        rows = (
            self._db.table("volunteers")
            .select("id, name")
            .in_("id", [str(i) for i in ids])
            .execute()
            .data
            or []
        )
        return {r["id"]: r.get("name") or "?" for r in rows}
