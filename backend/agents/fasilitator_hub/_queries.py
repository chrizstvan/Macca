"""Query mixin: cross-volunteer lookups, detail formatters, progress helpers."""

import logging
from datetime import datetime, timezone
from uuid import UUID

from backend.database.supabase_client import db

logger = logging.getLogger(__name__)


class QueryMixin:
    """Volunteer detail / cross-volunteer query entry points + formatters."""

    # ------------------------------------------------------------------ #
    # Volunteer detail / query                                            #
    # ------------------------------------------------------------------ #

    async def _handle_get_volunteer_detail(self, message: str) -> str:
        return await self.handle_volunteer_query(message, {"is_fasilitator": True})

    async def _handle_query_other_volunteer(self, message: str) -> str:
        return await self.handle_volunteer_query(message, {"is_fasilitator": True})

    # ------------------------------------------------------------------ #
    # Public cross-volunteer query handler                                #
    # ------------------------------------------------------------------ #

    async def handle_volunteer_query(
        self, message: str, context: dict
    ) -> str:
        """Cross-volunteer query entry point — respects peer-query policy."""
        from backend.utils.volunteer_resolver import (
            VolunteerResolver,
            can_query_volunteer,
        )

        resolver = VolunteerResolver(db, llm_caller=self.call_claude)
        targets = await resolver.extract_volunteer_mentions(message)

        # Filter targets the requester is allowed to see.
        requester_volunteer = context.get("volunteer") or {}
        requester_id = requester_volunteer.get("id")
        allowed: list[dict] = []
        denied: list[str] = []
        for target in targets:
            if can_query_volunteer(
                requester_id=requester_id,
                target_volunteer=target,
                context=context,
            ):
                allowed.append(target)
            else:
                denied.append(target.get("name") or "?")

        if denied and not allowed:
            return (
                "Hanya fasilitator yang bisa melihat data volunteer lain. "
                "Untuk lihat data kamu sendiri, tanyakan 'progress saya' "
                "atau 'apa tugas saya'."
            )

        if not allowed:
            if "siapa" in message.lower() and "lapor" in message.lower():
                return await self._handle_get_status()
            return (
                "Maksudnya volunteer yang mana? Sebutkan nama atau @username "
                "supaya saya bisa bantu."
            )

        full_view = bool(context.get("is_fasilitator"))
        if len(allowed) == 1:
            return await self._format_volunteer_query_single(
                allowed[0], full_view=full_view
            )
        return await self._format_volunteer_query_multi(
            allowed, full_view=full_view
        )

    # ------------------------------------------------------------------ #
    # Cross-volunteer formatters                                          #
    # ------------------------------------------------------------------ #

    async def _format_volunteer_query_single(
        self, volunteer: dict, *, full_view: bool
    ) -> str:
        total = await self._sum_reports_for(volunteer["id"])
        quota = float(volunteer.get("quota_kg") or 0)
        pct = (total / quota * 100) if quota else 0

        if not full_view:
            return (
                f"📋 Info volunteer: {volunteer.get('name')}\n"
                f"📍 Area: {volunteer.get('area') or '-'}\n"
                f"📦 Progress: {pct:.0f}% (dari kuota)"
            )

        mission = await self._active_mission_for(volunteer["id"])
        deadline = mission.deadline if (mission and mission.deadline) else "-"
        days_left = self._days_left_to(deadline)
        last_report = await self._last_report_for(volunteer["id"])
        last_line = (
            f"{last_report.reported_at.date().isoformat() if last_report.reported_at else '-'} — "
            f"{last_report.kg_collected.value:g} kg di "
            f"{last_report.location or '-'}"
            if last_report
            else "(belum ada laporan)"
        )
        team = volunteer.get("team") or []
        team_str = ", ".join(team) if team else "-"
        status_emoji, status_text = self._status_for_pct(pct)

        return (
            f"📋 Info volunteer: {volunteer.get('name')}\n"
            f"📍 Area: {volunteer.get('area') or '-'}\n"
            f"🎯 Kuota: {quota:g} kg\n"
            f"📦 Progress: {total:g}/{quota:g} kg ({pct:.0f}%)\n"
            f"⏰ Deadline: {deadline} ({days_left} hari lagi)\n"
            f"👥 Tim: {team_str}\n"
            f"📝 Laporan terakhir: {last_line}\n"
            f"Status: {status_emoji} {status_text}"
        )

    async def _format_volunteer_query_multi(
        self, volunteers: list[dict], *, full_view: bool
    ) -> str:
        names = " vs ".join(v.get("name") or "?" for v in volunteers)
        lines = [f"📊 Progress {names}:"]
        for v in volunteers:
            total = await self._sum_reports_for(v["id"])
            quota = float(v.get("quota_kg") or 0)
            pct = (total / quota * 100) if quota else 0
            if full_view:
                lines.append(
                    f"• {v.get('name')}: {total:g}/{quota:g} kg "
                    f"({pct:.0f}%) — {v.get('area') or '-'}"
                )
            else:
                lines.append(
                    f"• {v.get('name')}: {pct:.0f}% — {v.get('area') or '-'}"
                )
        return "\n".join(lines)

    async def _active_mission_for(self, volunteer_id):
        """Active Mission entity for a volunteer, or None."""
        from backend.infrastructure.composition_root import (
            build_mission_repository,
        )

        result = await build_mission_repository().get_active_for(
            UUID(str(volunteer_id))
        )
        return result[0] if result else None

    async def _last_report_for(self, volunteer_id):
        """Most recent Report entity for a volunteer, or None."""
        from backend.infrastructure.composition_root import (
            build_report_repository,
        )

        return await build_report_repository().latest_for_volunteer(
            UUID(str(volunteer_id))
        )

    @staticmethod
    def _days_left_to(deadline: str | None) -> int:
        if not deadline:
            return 0
        try:
            dt = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            return max((dt - datetime.now(timezone.utc)).days, 0)
        except Exception:
            return 0

    @staticmethod
    def _status_for_pct(pct: float) -> tuple[str, str]:
        if pct >= 100:
            return "🎉", "Selesai"
        if pct >= 75:
            return "🔥", "Hampir selesai"
        if pct >= 50:
            return "💪", "Setengah jalan"
        if pct > 0:
            return "🚀", "Sudah mulai"
        return "⚪", "Belum mulai"

    async def _find_volunteer_in_message(self, message: str) -> dict | None:
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        candidates = await build_volunteer_query_repository().list_active()
        return self._find_target_by_name(message, candidates)

    async def _format_volunteer_detail(
        self, volunteer: dict, *, brief: bool = False
    ) -> str:
        from backend.infrastructure.composition_root import (
            build_report_repository,
        )

        total = await self._sum_reports_for(volunteer["id"])
        quota = float(volunteer.get("quota_kg") or 0)
        pct = (total / quota * 100) if quota else 0
        rows = await build_report_repository().list_for_volunteer(
            UUID(str(volunteer["id"])), limit=3
        )
        last_lines = (
            "\n".join(
                f"  • {r.reported_at.date().isoformat() if r.reported_at else '-'}: "
                f"{r.kg_collected.value:g} kg @ {r.location or '-'}"
                for r in rows
            )
            or "  (belum ada laporan)"
        )
        head = (
            f"👤 {volunteer.get('name')}\n"
            f"📍 Area: {volunteer.get('area') or '-'}\n"
            f"📦 Progress: {total:g}/{quota:g} kg ({pct:.0f}%)"
        )
        if brief:
            return head
        return f"{head}\n📅 Laporan terakhir:\n{last_lines}"

    async def _sum_reports_for(self, volunteer_id) -> float:
        from backend.infrastructure.composition_root import (
            build_report_repository,
        )

        return await build_report_repository().total_kg_for_volunteer(
            UUID(str(volunteer_id))
        )
