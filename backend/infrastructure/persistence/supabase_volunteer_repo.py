"""Supabase-backed VolunteerRepository."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import Client

from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.domain.entities.volunteer import Volunteer
from backend.domain.value_objects.phone import Phone

from ._mappers import volunteer_from_row


class SupabaseVolunteerRepository(VolunteerRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def get_by_id(self, volunteer_id: UUID) -> Volunteer | None:
        rows = (
            self._db.table("volunteers")
            .select("*")
            .eq("id", str(volunteer_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return volunteer_from_row(rows[0]) if rows else None

    async def get_by_phone(self, phone: Phone) -> Volunteer | None:
        rows = (
            self._db.table("volunteers")
            .select("*")
            .eq("phone", phone.value)
            .limit(1)
            .execute()
            .data
            or []
        )
        return volunteer_from_row(rows[0]) if rows else None

    async def get_by_telegram_id(self, telegram_id: int) -> Volunteer | None:
        rows = (
            self._db.table("volunteers")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return volunteer_from_row(rows[0]) if rows else None

    async def list_active(self) -> list[Volunteer]:
        rows = (
            self._db.table("volunteers")
            .select("*")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        return [volunteer_from_row(r) for r in rows]

    async def list_for_mission(self, mission_id: UUID) -> list[Volunteer]:
        assignments = (
            self._db.table("volunteer_missions")
            .select("volunteer_id")
            .eq("mission_id", str(mission_id))
            .execute()
            .data
            or []
        )
        ids = [a["volunteer_id"] for a in assignments]
        if not ids:
            return []
        rows = (
            self._db.table("volunteers")
            .select("*")
            .in_("id", ids)
            .execute()
            .data
            or []
        )
        return [volunteer_from_row(r) for r in rows]

    async def find_by_name(self, name_fragment: str) -> list[Volunteer]:
        if not name_fragment:
            return []
        rows = (
            self._db.table("volunteers")
            .select("*")
            .ilike("name", f"%{name_fragment}%")
            .execute()
            .data
            or []
        )
        return [volunteer_from_row(r) for r in rows]

    async def save(self, volunteer: Volunteer) -> Volunteer:
        payload: dict[str, Any] = {
            "id": str(volunteer.id),
            "name": volunteer.name,
            "area": volunteer.area,
            "quota_kg": volunteer.quota_kg.value,
            "phone": volunteer.phone.value if volunteer.phone else None,
            "telegram_id": volunteer.telegram_id,
            "is_active": volunteer.is_active,
            "team": volunteer.team,
            "mission_query_count": volunteer.mission_query_count,
            "mission_query_reset_at": (
                volunteer.mission_query_reset_at.isoformat()
                if volunteer.mission_query_reset_at
                else None
            ),
            "whatsapp_connected": volunteer.whatsapp_connected,
            "first_contact_at": (
                volunteer.first_contact_at.isoformat()
                if volunteer.first_contact_at
                else None
            ),
            "last_contact_at": (
                volunteer.last_contact_at.isoformat()
                if volunteer.last_contact_at
                else None
            ),
        }
        result = (
            self._db.table("volunteers")
            .upsert(payload, on_conflict="id")
            .execute()
            .data
            or []
        )
        return volunteer_from_row(result[0]) if result else volunteer
