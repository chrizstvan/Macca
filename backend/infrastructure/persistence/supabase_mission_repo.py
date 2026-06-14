"""Supabase-backed MissionRepository."""

from __future__ import annotations

from uuid import UUID

from supabase import Client

from backend.application.ports.mission_repository import MissionRepository
from backend.domain.entities.mission import Mission, MissionAssignment

from ._mappers import assignment_from_row, mission_from_row


class SupabaseMissionRepository(MissionRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def get_active_for(
        self, volunteer_id: UUID
    ) -> tuple[Mission, MissionAssignment] | None:
        rows = (
            self._db.table("volunteer_missions")
            .select("quota_kg, assigned_area, reported_kg, missions(*)")
            .eq("volunteer_id", str(volunteer_id))
            .execute()
            .data
            or []
        )
        for row in rows:
            raw_mission = row.get("missions") or {}
            if raw_mission.get("status") != "active":
                continue
            mission = mission_from_row(raw_mission)
            assignment = assignment_from_row(
                row, volunteer_id=volunteer_id, mission_id=mission.id
            )
            return mission, assignment
        return None

    async def list_active(self) -> list[Mission]:
        rows = (
            self._db.table("missions")
            .select("*")
            .eq("status", "active")
            .execute()
            .data
            or []
        )
        return [mission_from_row(r) for r in rows]

    async def list_assignments(
        self, mission_id: UUID
    ) -> list[MissionAssignment]:
        rows = (
            self._db.table("volunteer_missions")
            .select("volunteer_id, quota_kg, assigned_area, reported_kg")
            .eq("mission_id", str(mission_id))
            .execute()
            .data
            or []
        )
        return [
            assignment_from_row(
                r,
                volunteer_id=UUID(r["volunteer_id"]),
                mission_id=mission_id,
            )
            for r in rows
        ]

    async def update_reported_kg(
        self, *, volunteer_id: UUID, mission_id: UUID, total_kg: float
    ) -> None:
        try:
            (
                self._db.table("volunteer_missions")
                .update({"reported_kg": total_kg})
                .eq("volunteer_id", str(volunteer_id))
                .eq("mission_id", str(mission_id))
                .execute()
            )
        except Exception:
            # Column requires the Part-7 migration; matches legacy tolerance.
            pass
