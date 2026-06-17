"""Query mixin: cross-volunteer lookups, detail formatters, progress helpers."""

import logging
from datetime import datetime, timezone

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
            return self._format_volunteer_query_single(
                allowed[0], full_view=full_view
            )
        return self._format_volunteer_query_multi(
            allowed, full_view=full_view
        )

    # ------------------------------------------------------------------ #
    # Cross-volunteer formatters                                          #
    # ------------------------------------------------------------------ #

    def _format_volunteer_query_single(
        self, volunteer: dict, *, full_view: bool
    ) -> str:
        total = self._sum_reports_for(volunteer["id"])
        quota = float(volunteer.get("quota_kg") or 0)
        pct = (total / quota * 100) if quota else 0

        if not full_view:
            return (
                f"📋 Info volunteer: {volunteer.get('name')}\n"
                f"📍 Area: {volunteer.get('area') or '-'}\n"
                f"📦 Progress: {pct:.0f}% (dari kuota)"
            )

        mission = self._active_mission_for(volunteer["id"])
        deadline = (mission or {}).get("deadline") or "-"
        days_left = self._days_left_to(deadline)
        last_report = self._last_report_for(volunteer["id"])
        last_line = (
            f"{last_report['reported_at'][:10]} — "
            f"{float(last_report['kg_collected']):g} kg di "
            f"{last_report.get('location') or '-'}"
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

    def _format_volunteer_query_multi(
        self, volunteers: list[dict], *, full_view: bool
    ) -> str:
        names = " vs ".join(v.get("name") or "?" for v in volunteers)
        lines = [f"📊 Progress {names}:"]
        for v in volunteers:
            total = self._sum_reports_for(v["id"])
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

    @staticmethod
    def _active_mission_for(volunteer_id: str) -> dict | None:
        rows = (
            db.table("volunteer_missions")
            .select("quota_kg, assigned_area, missions(*)")
            .eq("volunteer_id", volunteer_id)
            .execute()
            .data
            or []
        )
        for row in rows:
            m = row.get("missions") or {}
            if m.get("status") == "active":
                return m
        return None

    @staticmethod
    def _last_report_for(volunteer_id: str) -> dict | None:
        rows = (
            db.table("reports")
            .select("kg_collected, location, reported_at")
            .eq("volunteer_id", volunteer_id)
            .order("reported_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

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

    def _find_volunteer_in_message(self, message: str) -> dict | None:
        candidates = (
            db.table("volunteers")
            .select("id, name, area, quota_kg, phone, telegram_id")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        return self._find_target_by_name(message, candidates)

    def _format_volunteer_detail(
        self, volunteer: dict, *, brief: bool = False
    ) -> str:
        total = self._sum_reports_for(volunteer["id"])
        quota = float(volunteer.get("quota_kg") or 0)
        pct = (total / quota * 100) if quota else 0
        rows = (
            db.table("reports")
            .select("kg_collected, location, reported_at")
            .eq("volunteer_id", volunteer["id"])
            .order("reported_at", desc=True)
            .limit(3)
            .execute()
            .data
            or []
        )
        last_lines = (
            "\n".join(
                f"  • {r.get('reported_at', '')[:10]}: "
                f"{float(r['kg_collected']):g} kg @ {r.get('location') or '-'}"
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

    @staticmethod
    def _sum_reports_for(volunteer_id: str) -> float:
        rows = (
            db.table("reports")
            .select("kg_collected")
            .eq("volunteer_id", volunteer_id)
            .execute()
            .data
            or []
        )
        return sum(float(r.get("kg_collected") or 0) for r in rows)
