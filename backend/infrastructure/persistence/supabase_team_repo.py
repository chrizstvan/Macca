"""Supabase-backed TeamRepository — pure read aggregations."""

from __future__ import annotations

from uuid import UUID

from supabase import Client

from backend.application.ports.team_repository import TeamProgress, TeamRepository


def _coerce_team(value) -> str | None:
    """Match the volunteer-row coercion in ``_mappers._coerce_team``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            if item and str(item).strip():
                return str(item).strip()
        return None
    return str(value).strip() or None


class SupabaseTeamRepository(TeamRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def get_progress(
        self, *, team: str, mission_id: UUID
    ) -> TeamProgress:
        target = (team or "").strip()
        if not target:
            return TeamProgress(team="", member_count=0, total_quota_kg=0, reported_kg=0)

        member_rows = (
            self._db.table("volunteers")
            .select("id, team")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        member_ids = [
            v["id"] for v in member_rows if _coerce_team(v.get("team")) == target
        ]
        if not member_ids:
            return TeamProgress(
                team=target, member_count=0, total_quota_kg=0, reported_kg=0
            )

        assignments = (
            self._db.table("volunteer_missions")
            .select("quota_kg")
            .in_("volunteer_id", member_ids)
            .eq("mission_id", str(mission_id))
            .execute()
            .data
            or []
        )
        total_quota = sum(float(a.get("quota_kg") or 0) for a in assignments)

        reports = (
            self._db.table("reports")
            .select("kg_collected")
            .in_("volunteer_id", member_ids)
            .eq("mission_id", str(mission_id))
            .execute()
            .data
            or []
        )
        reported = sum(float(r.get("kg_collected") or 0) for r in reports)

        return TeamProgress(
            team=target,
            member_count=len(member_ids),
            total_quota_kg=round(total_quota, 2),
            reported_kg=round(reported, 2),
        )

    async def list_member_names(self, *, team: str) -> list[str]:
        target = (team or "").strip()
        if not target:
            return []
        rows = (
            self._db.table("volunteers")
            .select("name, team")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        return sorted(
            (r.get("name") or "?")
            for r in rows
            if _coerce_team(r.get("team")) == target
        )
