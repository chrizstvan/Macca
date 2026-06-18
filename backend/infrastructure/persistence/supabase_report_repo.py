"""Supabase-backed ReportRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from supabase import Client

from backend.application.ports.report_repository import ReportRepository
from backend.domain.entities.report import Report
from backend.domain.value_objects.kg import Kg

from ._mappers import report_from_row, report_to_row


def _today_start_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


class SupabaseReportRepository(ReportRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def insert(self, report: Report) -> Report:
        payload = report_to_row(report)
        # Drop the sentinel id so Postgres assigns a real UUID.
        payload.pop("id", None)
        result = (
            self._db.table("reports").insert(payload).execute().data or []
        )
        return report_from_row(result[0]) if result else report

    async def update(
        self,
        report_id: UUID,
        *,
        kg: Kg,
        location: str,
        photo_url: str | None = None,
    ) -> None:
        update = {"kg_collected": kg.value, "location": location}
        if photo_url is not None:
            update["photo_url"] = photo_url
        self._db.table("reports").update(update).eq("id", str(report_id)).execute()

    async def find_latest_today(
        self, volunteer_id: UUID, mission_id: UUID
    ) -> Report | None:
        rows = (
            self._db.table("reports")
            .select("*")
            .eq("volunteer_id", str(volunteer_id))
            .eq("mission_id", str(mission_id))
            .gte("reported_at", _today_start_iso())
            .order("reported_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return report_from_row(rows[0]) if rows else None

    async def find_similar_today(
        self,
        volunteer_id: UUID,
        mission_id: UUID,
        *,
        kg: Kg,
        tolerance_kg: float = 1.0,
    ) -> Report | None:
        rows = (
            self._db.table("reports")
            .select("*")
            .eq("volunteer_id", str(volunteer_id))
            .eq("mission_id", str(mission_id))
            .gte("reported_at", _today_start_iso())
            .execute()
            .data
            or []
        )
        for row in rows:
            if abs(float(row["kg_collected"]) - kg.value) < tolerance_kg:
                return report_from_row(row)
        return None

    async def total_kg_for(
        self, volunteer_id: UUID, mission_id: UUID
    ) -> float:
        rows = (
            self._db.table("reports")
            .select("kg_collected")
            .eq("volunteer_id", str(volunteer_id))
            .eq("mission_id", str(mission_id))
            .execute()
            .data
            or []
        )
        return sum(float(r["kg_collected"]) for r in rows)

    async def list_for_mission(
        self, mission_id: UUID, *, limit: int | None = None
    ) -> list[Report]:
        query = (
            self._db.table("reports")
            .select("*")
            .eq("mission_id", str(mission_id))
            .order("reported_at", desc=True)
        )
        if limit:
            query = query.limit(limit)
        rows = query.execute().data or []
        return [report_from_row(r) for r in rows]

    async def list_for_volunteer_in_mission(
        self, volunteer_id: UUID, mission_id: UUID
    ) -> list[Report]:
        rows = (
            self._db.table("reports")
            .select("*")
            .eq("volunteer_id", str(volunteer_id))
            .eq("mission_id", str(mission_id))
            .order("reported_at", desc=True)
            .execute()
            .data
            or []
        )
        return [report_from_row(r) for r in rows]

    async def program_total_kg(self, mission_id: UUID) -> float:
        rows = (
            self._db.table("reports")
            .select("kg_collected")
            .eq("mission_id", str(mission_id))
            .neq("verified", False)
            .execute()
            .data
            or []
        )
        return sum(float(r["kg_collected"]) for r in rows)

    async def count_reporters_today(self, mission_id: UUID) -> int:
        rows = (
            self._db.table("reports")
            .select("volunteer_id")
            .eq("mission_id", str(mission_id))
            .gte("reported_at", _today_start_iso())
            .execute()
            .data
            or []
        )
        return len({r["volunteer_id"] for r in rows})

    async def total_kg_for_volunteer(self, volunteer_id: UUID) -> float:
        rows = (
            self._db.table("reports")
            .select("kg_collected")
            .eq("volunteer_id", str(volunteer_id))
            .execute()
            .data
            or []
        )
        return sum(float(r.get("kg_collected") or 0) for r in rows)

    async def latest_for_volunteer(
        self, volunteer_id: UUID
    ) -> Report | None:
        rows = (
            self._db.table("reports")
            .select("*")
            .eq("volunteer_id", str(volunteer_id))
            .order("reported_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return report_from_row(rows[0]) if rows else None

    async def list_for_volunteer(
        self, volunteer_id: UUID, *, limit: int | None = None
    ) -> list[Report]:
        query = (
            self._db.table("reports")
            .select("*")
            .eq("volunteer_id", str(volunteer_id))
            .order("reported_at", desc=True)
        )
        if limit:
            query = query.limit(limit)
        rows = query.execute().data or []
        return [report_from_row(r) for r in rows]

    async def list_all(self) -> list[Report]:
        rows = (
            self._db.table("reports").select("*").execute().data or []
        )
        return [report_from_row(r) for r in rows]

    async def list_today(self) -> list[Report]:
        rows = (
            self._db.table("reports")
            .select("*")
            .gte("reported_at", _today_start_iso())
            .execute()
            .data
            or []
        )
        return [report_from_row(r) for r in rows]

    async def list_between(
        self, start: datetime, end: datetime
    ) -> list[Report]:
        rows = (
            self._db.table("reports")
            .select("*")
            .gte("reported_at", start.isoformat())
            .lt("reported_at", end.isoformat())
            .execute()
            .data
            or []
        )
        return [report_from_row(r) for r in rows]

    async def count_flagged_unverified(self) -> int:
        rows = (
            self._db.table("reports")
            .select("id")
            .eq("is_flagged", True)
            .eq("verified", False)
            .execute()
            .data
            or []
        )
        return len(rows)

    async def list_flagged_unverified(self) -> list[Report]:
        rows = (
            self._db.table("reports")
            .select("*")
            .eq("is_flagged", True)
            .eq("verified", False)
            .order("reported_at", desc=True)
            .execute()
            .data
            or []
        )
        return [report_from_row(r) for r in rows]
