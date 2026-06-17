"""Command mixin: intent classify/dispatch, reminders, status, mission CRUD, broadcast."""

import logging
import re
from datetime import datetime, timedelta, timezone

from backend.database.supabase_client import db

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
        rows = (
            db.table("volunteers")
            .select("id, name, area, quota_kg, phone, telegram_id")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        if not rows:
            return "Belum ada volunteer aktif untuk dikirimi reminder."

        if only_non_reporters:
            today_start = (
                datetime.now(timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )
            reports_today = (
                db.table("reports")
                .select("volunteer_id")
                .gte("reported_at", today_start)
                .execute()
                .data
                or []
            )
            reported_ids = {r["volunteer_id"] for r in reports_today}
            rows = [v for v in rows if v["id"] not in reported_ids]
            if not rows:
                return (
                    "✅ Semua volunteer sudah lapor hari ini — "
                    "tidak ada reminder yang dikirim."
                )

        kind = subtype or "custom"
        recipients_named: list[str] = []
        for v in rows:
            reported_kg = self._sum_reports_for(v["id"])
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
        volunteers = (
            db.table("volunteers")
            .select("id, name, area")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        reports_today = (
            db.table("reports")
            .select("volunteer_id, kg_collected, location")
            .gte("reported_at", today_start)
            .execute()
            .data
            or []
        )
        kg_total_today = sum(
            float(r.get("kg_collected") or 0) for r in reports_today
        )
        reporters_today = {r["volunteer_id"] for r in reports_today}
        non_reporters = [
            v.get("name", "?")
            for v in volunteers
            if v["id"] not in reporters_today
        ]
        flagged = (
            db.table("reports")
            .select("id")
            .eq("is_flagged", True)
            .eq("verified", False)
            .execute()
            .data
            or []
        )
        locations = sorted({(r.get("location") or "").strip() for r in reports_today if r.get("location")})

        return (
            "📊 Status program hari ini:\n"
            f"📦 Total: {kg_total_today:g} kg\n"
            f"✅ Sudah lapor: {len(reporters_today)}/{len(volunteers)}\n"
            f"⚠️ Belum lapor: {', '.join(non_reporters[:10]) or '-'}\n"
            f"🚩 Laporan flagged (perlu review): {len(flagged)}\n"
            f"📍 Area aktif: {', '.join(locations) or '-'}"
        )

    async def _handle_get_analytics(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.impact_analyzer import ImpactAnalyzerAgent

        return await ImpactAnalyzerAgent().process(message, context)

    async def _handle_flag_review(self) -> str:
        rows = (
            db.table("reports")
            .select(
                "id, kg_collected, location, flag_reason, reported_at, "
                "volunteer_id"
            )
            .eq("is_flagged", True)
            .eq("verified", False)
            .order("reported_at", desc=True)
            .execute()
            .data
            or []
        )
        if not rows:
            return "✅ Tidak ada laporan flagged yang perlu direview saat ini."

        names = self._fetch_names_for(
            [r["volunteer_id"] for r in rows if r.get("volunteer_id")]
        )
        lines = []
        for r in rows[:10]:
            name = names.get(r.get("volunteer_id"), "?")
            kg = float(r.get("kg_collected") or 0)
            loc = r.get("location") or "-"
            reason = r.get("flag_reason") or "tidak ada alasan tercatat"
            lines.append(f"• {name}: {kg:g} kg @ {loc} — {reason}")
        return (
            f"🚩 Laporan flagged ({len(rows)} total, tampilkan 10 teratas):\n"
            + "\n".join(lines)
            + "\n\nApakah ingin saya approve atau reject? Sebutkan ID atau nama."
        )

    @staticmethod
    def _fetch_names_for(ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        rows = (
            db.table("volunteers")
            .select("id, name")
            .in_("id", ids)
            .execute()
            .data
            or []
        )
        return {r["id"]: r.get("name") or "?" for r in rows}

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
        rows = (
            db.table("volunteers")
            .select("id, name, phone, telegram_id")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
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

        row = {
            "title": title,
            "description": payload.get("description") or "",
            "status": "active",
        }
        deadline = payload.get("deadline")
        if deadline:
            row["deadline"] = deadline

        try:
            inserted = (
                db.table("missions").insert(row).execute().data or []
            )
        except Exception as exc:
            return f"Gagal membuat misi: {exc}"

        if not inserted:
            return "Gagal membuat misi (tidak ada baris dikembalikan)."
        mid = inserted[0]["id"]
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

        vol_rows = (
            db.table("volunteers")
            .select("id, name")
            .ilike("name", f"%{volunteer_name}%")
            .execute()
            .data
            or []
        )
        if not vol_rows:
            return f"Volunteer '{volunteer_name}' tidak ditemukan."
        if len(vol_rows) > 1:
            names = ", ".join(v["name"] for v in vol_rows)
            return f"Ada beberapa volunteer cocok: {names}. Sebutkan nama lengkap."
        volunteer = vol_rows[0]

        mission_rows = (
            db.table("missions")
            .select("id, title")
            .ilike("title", f"%{mission_hint}%")
            .eq("status", "active")
            .execute()
            .data
            or []
        )
        if not mission_rows:
            return f"Misi yang cocok dengan '{mission_hint}' tidak ditemukan."
        mission = mission_rows[0]

        quota_kg = payload.get("quota_kg")
        row = {
            "volunteer_id": volunteer["id"],
            "mission_id": mission["id"],
            "assigned_area": mission_hint,
        }
        if quota_kg:
            row["quota_kg"] = quota_kg

        try:
            db.table("volunteer_missions").insert(row).execute()
        except Exception as exc:
            return f"Assignment gagal: {exc}"

        suffix = f" (kuota {quota_kg:g} kg)" if quota_kg else ""
        return (
            f"✅ {volunteer['name']} ditugaskan ke misi '{mission['title']}'"
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

        volunteers = (
            db.table("volunteers")
            .select("id, name")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        yesterday_start = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        reports_yest = (
            db.table("reports")
            .select("volunteer_id, kg_collected")
            .gte("reported_at", yesterday_start)
            .lt("reported_at", today_start)
            .execute()
            .data
            or []
        )
        kg_yest = sum(float(r.get("kg_collected") or 0) for r in reports_yest)
        reporters_yest = {r["volunteer_id"] for r in reports_yest}
        non_reporters = [
            v.get("name", "?")
            for v in volunteers
            if v["id"] not in reporters_yest
        ]

        program_total = sum(
            float(r.get("kg_collected") or 0)
            for r in (
                db.table("reports").select("kg_collected").execute().data or []
            )
        )
        target_kg = sum(
            float(r.get("quota_kg") or 0)
            for r in (
                db.table("volunteer_missions")
                .select("quota_kg")
                .execute()
                .data
                or []
            )
        )
        pct = (program_total / target_kg * 100) if target_kg else 0

        flagged = (
            db.table("reports")
            .select("id")
            .eq("is_flagged", True)
            .eq("verified", False)
            .execute()
            .data
            or []
        )

        non_rep_str = (
            ", ".join(non_reporters[:6])
            + (f" +{len(non_reporters) - 6} lainnya" if len(non_reporters) > 6 else "")
            if non_reporters
            else "(semua sudah lapor 🎉)"
        )

        active_missions = (
            db.table("missions")
            .select("title, deadline")
            .eq("status", "active")
            .execute()
            .data
            or []
        )
        now = datetime.now(timezone.utc)
        deadline_lines: list[str] = []
        for m in active_missions:
            raw = m.get("deadline")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            days_left = max((dt - now).days, 0)
            deadline_lines.append(
                f"  • {m.get('title') or 'Misi'}: {days_left} hari lagi"
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
            f"⚠️ Perlu perhatian: {len(flagged)} laporan flagged\n"
            f"🔔 Belum lapor: {non_rep_str}"
            f"{deadline_block}"
        )
        await alert_fasilitator(briefing)
        return briefing
