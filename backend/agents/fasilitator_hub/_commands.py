"""Command mixin: intent classify/dispatch, reminders, status, mission CRUD, broadcast."""

import logging
import re
from datetime import datetime, timedelta, timezone

from ..base_agent import COMPLEX_MODEL
from ._constants import FAS_INTENTS, INTENT_CLASSIFY_PROMPT, REMIND_TEMPLATES, SUGGESTIONS

logger = logging.getLogger(__name__)


class CommandMixin:
    """Phase 6 intent classifier + the dedicated operational command handlers."""

    # ------------------------------------------------------------------ #
    # Phase 6 — intent classifier + suggestions                          #
    # ------------------------------------------------------------------ #

    async def _classify_command(self, message: str) -> str:
        """Sonnet-classified command label; ``default`` for free-form chat."""
        if not message or not message.strip():
            return "default"
        verdict = await self.call_claude(
            INTENT_CLASSIFY_PROMPT,
            [{"role": "user", "content": message}],
            model=COMPLEX_MODEL,
            max_tokens=10,
        )
        label = (verdict or "").strip().lower().split()[0:1]
        candidate = label[0] if label else "default"
        candidate = candidate.replace("`", "").replace("'", "").replace('"', "")
        return candidate if candidate in FAS_INTENTS else "default"

    @staticmethod
    def _append_suggestions(reply: str, intent: str) -> str:
        opts = SUGGESTIONS.get(intent, SUGGESTIONS["default"])
        bullets = "\n".join(f"• {o}" for o in opts[:3])
        sep = "" if reply.endswith("\n") else "\n"
        return f"{reply}{sep}\n💡 Mau lanjut:\n{bullets}"

    async def _dispatch_intent(
        self, intent: str, message: str, context: dict
    ) -> str:
        handlers = {
            "send_reminder": lambda: self._handle_send_reminder_free(message),
            "get_status": lambda: self._handle_get_status(),
            "get_analytics": lambda: self._handle_get_analytics(message, context),
            "create_mission": lambda: self._handle_create_mission(message),
            "assign_volunteer": lambda: self._handle_assign_volunteer(message),
            "broadcast": lambda: self._handle_broadcast(message),
            "flag_review": lambda: self._handle_flag_review(),
            "generate_report": lambda: self._handle_generate_report(message, context),
            "generate_content": lambda: self._handle_generate_content(message, context),
            "get_volunteer_detail": lambda: self._handle_get_volunteer_detail(message),
            "query_other_volunteer": lambda: self._handle_query_other_volunteer(message),
            "save_report_for": lambda: self._handle_save_report_for(message, context),
        }
        return await handlers[intent]()

    # ------------------------------------------------------------------ #
    # /remind slash + free-text send_reminder                             #
    # ------------------------------------------------------------------ #

    async def _handle_remind_slash(
        self, *, subtype: str | None, arg: str, only_non_reporters: bool = False
    ) -> str:
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        rows = await build_volunteer_query_repository().list_active()
        if not rows:
            return "Belum ada volunteer aktif untuk dikirimi reminder."

        if only_non_reporters:
            from backend.infrastructure.composition_root import (
                build_report_repository,
            )

            reports_today = await build_report_repository().list_today()
            reported_ids = {str(r.volunteer_id) for r in reports_today}
            rows = [v for v in rows if str(v["id"]) not in reported_ids]
            if not rows:
                return (
                    "✅ Semua volunteer sudah lapor hari ini — "
                    "tidak ada reminder yang dikirim."
                )

        kind = subtype or "custom"
        recipients_named: list[str] = []
        for v in rows:
            reported_kg = await self._sum_reports_for(v["id"])
            text = self._format_reminder_text(
                kind=kind,
                arg=arg,
                name=v.get("name") or "Volunteer",
                area=v.get("area") or "-",
                quota_kg=float(v.get("quota_kg") or 0),
                reported_kg=reported_kg,
            )
            await self._notify_volunteer_dict(v, text)
            recipients_named.append(v.get("name") or "?")
        return (
            f"✅ Reminder ({kind}) dikirim ke {len(rows)} volunteer: "
            + ", ".join(recipients_named)
        )

    async def _handle_send_reminder_free(self, message: str) -> str:
        """Free-text reminder routing (no slash). Defaults to progress reminder.

        When the fasilitator scopes the request to "yang belum lapor" we
        filter recipients to volunteers without a report today.
        """
        lowered = message.lower()
        only_non_reporters = (
            "belum lapor" in lowered
            or "belum report" in lowered
            or "yang belum" in lowered
        )
        return await self._handle_remind_slash(
            subtype="progress",
            arg=message,
            only_non_reporters=only_non_reporters,
        )

    @staticmethod
    def _format_reminder_text(
        *,
        kind: str,
        arg: str,
        name: str,
        area: str,
        quota_kg: float,
        reported_kg: float,
    ) -> str:
        template = REMIND_TEMPLATES.get(kind, REMIND_TEMPLATES["custom"])
        return template.format(
            name=name,
            arg=arg or "—",
            area=area,
            quota_kg=quota_kg,
            reported_kg=reported_kg,
        )

    @staticmethod
    async def _notify_volunteer_dict(volunteer: dict, text: str) -> None:
        from backend.agents.services.notifications import notify_volunteer

        await notify_volunteer(volunteer, text)

    # ------------------------------------------------------------------ #
    # Status / analytics / flag review                                    #
    # ------------------------------------------------------------------ #

    async def _handle_get_status(self) -> str:
        from backend.infrastructure.composition_root import (
            build_report_repository,
            build_volunteer_query_repository,
        )

        volunteers = await build_volunteer_query_repository().list_active()
        reports_repo = build_report_repository()
        reports_today = await reports_repo.list_today()
        kg_total_today = sum(r.kg_collected.value for r in reports_today)
        reporters_today = {str(r.volunteer_id) for r in reports_today}
        non_reporters = [
            v.get("name", "?")
            for v in volunteers
            if str(v["id"]) not in reporters_today
        ]
        flagged_count = await reports_repo.count_flagged_unverified()
        locations = sorted(
            {(r.location or "").strip() for r in reports_today if r.location}
        )

        return (
            "📊 Status program hari ini:\n"
            f"📦 Total: {kg_total_today:g} kg\n"
            f"✅ Sudah lapor: {len(reporters_today)}/{len(volunteers)}\n"
            f"⚠️ Belum lapor: {', '.join(non_reporters[:10]) or '-'}\n"
            f"🚩 Laporan flagged (perlu review): {flagged_count}\n"
            f"📍 Area aktif: {', '.join(locations) or '-'}"
        )

    async def _handle_get_analytics(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.impact_analyzer import ImpactAnalyzerAgent

        return await ImpactAnalyzerAgent().process(message, context)

    async def _handle_flag_review(self) -> str:
        from backend.infrastructure.composition_root import (
            build_report_repository,
        )

        rows = await build_report_repository().list_flagged_unverified()
        if not rows:
            return "✅ Tidak ada laporan flagged yang perlu direview saat ini."

        names = await self._fetch_names_for(
            [str(r.volunteer_id) for r in rows if r.volunteer_id]
        )
        lines = []
        for r in rows[:10]:
            name = names.get(str(r.volunteer_id), "?")
            kg = r.kg_collected.value
            loc = r.location or "-"
            reason = r.flag_reason or "tidak ada alasan tercatat"
            lines.append(f"• {name}: {kg:g} kg @ {loc} — {reason}")
        return (
            f"🚩 Laporan flagged ({len(rows)} total, tampilkan 10 teratas):\n"
            + "\n".join(lines)
            + "\n\nApakah ingin saya approve atau reject? Sebutkan ID atau nama."
        )

    @staticmethod
    async def _fetch_names_for(ids: list[str]) -> dict[str, str]:
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        return await build_volunteer_query_repository().names_for(ids)

    # ------------------------------------------------------------------ #
    # Broadcast                                                            #
    # ------------------------------------------------------------------ #

    async def _handle_broadcast(self, message: str) -> str:
        # Extract the broadcast text — drop leading "broadcast", "umumkan", etc.
        text = re.sub(
            r"^(broadcast|umumkan(?:\s+ke\s+semua)?|kirim\s+ke\s+semua)[:,]?\s*",
            "",
            message.strip(),
            flags=re.IGNORECASE,
        )
        if not text or len(text) < 5:
            return "Broadcast tidak terkirim. Ketik: 'broadcast: <pesan>' (minimum 5 karakter)."
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        rows = await build_volunteer_query_repository().list_active()
        if not rows:
            return "Belum ada volunteer aktif sebagai penerima broadcast."
        for v in rows:
            await self._notify_volunteer_dict(v, text)
        return f"📢 Broadcast terkirim ke {len(rows)} volunteer."

    # ------------------------------------------------------------------ #
    # Create mission / assign volunteer                                   #
    # ------------------------------------------------------------------ #

    _MISSION_EXTRACT_PROMPT = (
        "Dari pesan fasilitator, ekstrak metadata misi baru sebagai JSON valid "
        "dengan kunci: title (string), description (string boleh kosong), "
        "deadline (ISO date YYYY-MM-DD jika ada, else null), quota_kg (number "
        "jika ada, else null). Balas HANYA JSON. Tidak ada teks lain."
    )

    async def _handle_create_mission(self, message: str) -> str:
        import json as _json

        try:
            raw = await self.call_claude(
                self._MISSION_EXTRACT_PROMPT,
                [{"role": "user", "content": message}],
                model=COMPLEX_MODEL,
                max_tokens=200,
            )
            payload_match = re.search(r"\{.*\}", raw, re.DOTALL)
            payload = _json.loads(payload_match.group(0)) if payload_match else {}
        except Exception as exc:
            logger.warning("create_mission extract failed: %s", exc)
            payload = {}

        title = (payload.get("title") or "").strip()
        if not title:
            return (
                "Aku butuh judul misi yang jelas. Contoh: 'buat misi "
                "pengumpulan PET di Cikini sampai 30 Juli, kuota 20 kg.'"
            )

        from backend.infrastructure.composition_root import (
            build_mission_repository,
        )

        try:
            mission = await build_mission_repository().create(
                title=title,
                description=payload.get("description") or "",
                deadline=payload.get("deadline"),
            )
        except Exception as exc:
            return f"Gagal membuat misi: {exc}"

        mid = str(mission.id)
        return (
            f"✅ Misi '{title}' dibuat (id={mid[:8]}...). "
            "Tambahkan assignment volunteer dengan: 'tugaskan <nama> ke "
            f"{title}'."
        )

    _ASSIGN_EXTRACT_PROMPT = (
        "Dari pesan fasilitator, ekstrak data assignment sebagai JSON: "
        "{volunteer_name: string, mission_title_or_area: string, "
        "quota_kg: number atau null}. Balas hanya JSON."
    )

    async def _handle_assign_volunteer(self, message: str) -> str:
        import json as _json

        try:
            raw = await self.call_claude(
                self._ASSIGN_EXTRACT_PROMPT,
                [{"role": "user", "content": message}],
                model=COMPLEX_MODEL,
                max_tokens=160,
            )
            payload_match = re.search(r"\{.*\}", raw, re.DOTALL)
            payload = _json.loads(payload_match.group(0)) if payload_match else {}
        except Exception as exc:
            logger.warning("assign extract failed: %s", exc)
            payload = {}

        volunteer_name = (payload.get("volunteer_name") or "").strip()
        mission_hint = (payload.get("mission_title_or_area") or "").strip()
        if not volunteer_name or not mission_hint:
            return (
                "Aku butuh nama volunteer + nama misi/area target. Contoh: "
                "'tugaskan Budi ke misi PET Cikini'."
            )

        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        vol_rows = await build_volunteer_query_repository().find_by_name(
            volunteer_name
        )
        if not vol_rows:
            return f"Volunteer '{volunteer_name}' tidak ditemukan."
        if len(vol_rows) > 1:
            names = ", ".join(v["name"] for v in vol_rows)
            return f"Ada beberapa volunteer cocok: {names}. Sebutkan nama lengkap."
        volunteer = vol_rows[0]

        from uuid import UUID

        from backend.infrastructure.composition_root import (
            build_mission_repository,
        )

        missions_repo = build_mission_repository()
        mission_rows = await missions_repo.find_active_by_title(mission_hint)
        if not mission_rows:
            return f"Misi yang cocok dengan '{mission_hint}' tidak ditemukan."
        mission = mission_rows[0]

        quota_kg = payload.get("quota_kg")
        try:
            await missions_repo.add_assignment(
                volunteer_id=UUID(str(volunteer["id"])),
                mission_id=mission.id,
                assigned_area=mission_hint,
                quota_kg=quota_kg,
            )
        except Exception as exc:
            return f"Assignment gagal: {exc}"

        suffix = f" (kuota {quota_kg:g} kg)" if quota_kg else ""
        return (
            f"✅ {volunteer['name']} ditugaskan ke misi '{mission.title}'"
            f"{suffix}."
        )

    # ------------------------------------------------------------------ #
    # Report / content delegation                                         #
    # ------------------------------------------------------------------ #

    async def _handle_generate_report(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.impact_analyzer import ImpactAnalyzerAgent

        return await ImpactAnalyzerAgent().process(message, context)

    async def _handle_generate_content(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.content_creator import ContentCreatorAgent

        return await ContentCreatorAgent().process(message, context)

    # ------------------------------------------------------------------ #
    # Scheduled morning briefing                                          #
    # ------------------------------------------------------------------ #

    async def get_morning_briefing(self) -> str:
        from backend.agents.services.notifications import alert_fasilitator

        from backend.infrastructure.composition_root import (
            build_report_repository,
            build_volunteer_query_repository,
        )

        volunteers = await build_volunteer_query_repository().list_active()

        yesterday_start = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        reports_repo = build_report_repository()
        reports_yest = await reports_repo.list_between(yesterday_start, today_start)
        kg_yest = sum(r.kg_collected.value for r in reports_yest)
        reporters_yest = {str(r.volunteer_id) for r in reports_yest}
        non_reporters = [
            v.get("name", "?")
            for v in volunteers
            if str(v["id"]) not in reporters_yest
        ]

        program_total = sum(
            r.kg_collected.value for r in await reports_repo.list_all()
        )
        from backend.infrastructure.composition_root import (
            build_mission_repository,
        )

        missions_repo = build_mission_repository()
        target_kg = await missions_repo.total_assigned_quota()
        pct = (program_total / target_kg * 100) if target_kg else 0

        flagged_count = await reports_repo.count_flagged_unverified()

        non_rep_str = (
            ", ".join(non_reporters[:6])
            + (f" +{len(non_reporters) - 6} lainnya" if len(non_reporters) > 6 else "")
            if non_reporters
            else "(semua sudah lapor 🎉)"
        )

        active_missions = await missions_repo.list_active()
        today = datetime.now(timezone.utc).date()
        deadline_lines: list[str] = []
        for m in active_missions:
            if not m.deadline:
                continue
            days_left = max((m.deadline - today).days, 0)
            deadline_lines.append(
                f"  • {m.title or 'Misi'}: {days_left} hari lagi"
            )
        deadline_block = (
            "\n⏰ Deadline misi aktif:\n" + "\n".join(deadline_lines)
            if deadline_lines
            else ""
        )

        briefing = (
            "🌅 Morning briefing:\n"
            f"📦 Total terkumpul (program): {program_total:g} kg "
            f"({pct:.0f}% dari target {target_kg:g} kg)\n"
            f"📈 Kemarin: {kg_yest:g} kg dari {len(reporters_yest)} volunteer\n"
            f"✅ Sudah lapor kemarin: {len(reporters_yest)}/{len(volunteers)} "
            "volunteer\n"
            f"⚠️ Perlu perhatian: {flagged_count} laporan flagged\n"
            f"🔔 Belum lapor: {non_rep_str}"
            f"{deadline_block}"
        )
        await alert_fasilitator(briefing)
        return briefing
