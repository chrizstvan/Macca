"""Progress tracker agent: parses collection reports (chat + Google Form) and answers progress queries."""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from backend.config import settings
from backend.database.supabase_client import db
from backend.utils.impact_calculator import ImpactCalculator
from .base_agent import BaseAgent
from .prompts.progress_tracker import PARSE_PROMPT

logger = logging.getLogger(__name__)

PENDING_TTL = timedelta(minutes=10)

INQUIRY_KEYWORDS = (
    "berapa", "sudah berapa", "progress", "total", "sisa",
    "kuota", "pencapaian", "sudah sampai mana",
)

KG_FIELDS = ("Berat Plastik (kg)", "Berat (kg)", "Kg", "Berat")
LOC_FIELDS = ("Lokasi Pengumpulan", "Lokasi", "Area", "Kelurahan")
TYPE_FIELDS = ("Jenis Plastik", "Tipe Plastik", "Jenis")
PHOTO_FIELDS = ("Foto", "Upload Foto", "Dokumentasi")
NOTES_FIELDS = ("Catatan", "Keterangan", "Notes")

ASK_FORMAT_MSG = (
    "Boleh ulangi laporannya dengan format:\n"
    "'Laporan [berat] kg [lokasi]'\n"
    "Contoh: 'Laporan 18 kg Menteng' 🙏"
)
ASK_KG_AND_LOCATION_MSG = (
    "Terima kasih fotonya! Boleh kasih tahu beratnya berapa kg "
    "dan lokasinya di mana? 😊"
)

# ------------------------------------------------------------------------- #
# Pending state (Part 5) — in-memory, keyed by telegram_id, 10-minute TTL    #
# ------------------------------------------------------------------------- #

pending_reports: dict[int, dict] = {}


def _set_pending(
    telegram_id: int | None,
    step: str,
    data: dict,
    existing_report_id: str | None = None,
) -> None:
    if telegram_id is None:
        return
    pending_reports[telegram_id] = {
        "step": step,  # waiting_kg | waiting_location | waiting_confirmation
        "data": data,
        "existing_report_id": existing_report_id,
        "expires_at": datetime.now(timezone.utc) + PENDING_TTL,
    }


def has_pending_report(telegram_id: int | None) -> bool:
    """True if the volunteer has an unexpired pending report state."""
    entry = pending_reports.get(telegram_id)
    if entry is None:
        return False
    if entry["expires_at"] < datetime.now(timezone.utc):
        del pending_reports[telegram_id]
        return False
    return True


async def cleanup_expired_pending() -> None:
    """Scheduler job: drop expired pending states (runs every 5 minutes)."""
    now = datetime.now(timezone.utc)
    expired = [key for key, entry in pending_reports.items() if entry["expires_at"] < now]
    for key in expired:
        del pending_reports[key]
    if expired:
        logger.info("Cleaned up %d expired pending report state(s)", len(expired))


async def _alert_fasilitator(text: str) -> None:
    """DM the fasilitator via the Telegram HTTP API (works outside PTB handlers too)."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                url, json={"chat_id": settings.fasilitator_telegram_id, "text": text}
            )
    except Exception as exc:
        logger.error("Failed to alert fasilitator: %s", exc)


def _get_field(data: dict, candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        if key in data and data[key]:
            return str(data[key]).strip()
    return None


class ProgressTrackerAgent(BaseAgent):
    """Turns chat messages and Google Form submissions into rows in the reports table."""

    def __init__(self) -> None:
        super().__init__(
            name="progress_tracker",
            description="Parses collection reports and answers progress inquiries",
        )

    # --------------------------------------------------------------------- #
    # Part 1 — entry point                                                    #
    # --------------------------------------------------------------------- #

    async def process(self, message: str, context: dict) -> str:
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)

        if context.get("persona") == "fasilitator":
            return await self._program_summary(context)

        source = context.get("source", "chat")
        if source == "google_form":
            return await self.process_form_submission(context["form_data"], context)

        telegram_id = context.get("telegram_id")
        if telegram_id and has_pending_report(telegram_id):
            reply = await self._resume_pending(message, context)
        elif self.is_progress_inquiry(message):
            reply = await self.process_progress_inquiry(context)
        else:
            reply = await self.process_chat_report(message, context)

        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply

    @staticmethod
    def is_progress_inquiry(message: str) -> bool:
        lowered = message.lower()
        return any(keyword in lowered for keyword in INQUIRY_KEYWORDS)

    # --------------------------------------------------------------------- #
    # Part 2 — chat report (Telegram / WhatsApp)                              #
    # --------------------------------------------------------------------- #

    async def process_chat_report(self, message: str, context: dict) -> str:
        telegram_id = context.get("telegram_id")
        photo_url = context.get("photo_url")
        kg, location = await self._parse_report(message)

        if kg is None and photo_url:
            _set_pending(
                telegram_id,
                "waiting_kg",
                {"kg": None, "location": location, "photo_url": photo_url},
            )
            return ASK_KG_AND_LOCATION_MSG
        if kg is None:
            return ASK_FORMAT_MSG
        if location is None:
            _set_pending(
                telegram_id,
                "waiting_location",
                {"kg": kg, "location": None, "photo_url": photo_url},
            )
            return f"Berat {kg:g} kg tercatat! Lokasinya di mana ya? 📍"

        return await self._finalize(
            context, kg, location, photo_url, raw_message=message,
            source=context.get("channel", "telegram"),
        )

    async def _resume_pending(self, message: str, context: dict) -> str:
        """Part 5 — complete (or correct) a report using the saved pending state."""
        telegram_id = context["telegram_id"]
        entry = pending_reports.pop(telegram_id)
        data = entry["data"]

        if entry["step"] == "waiting_confirmation":
            choice = message.strip().lower()
            if choice.startswith("a"):
                return await self._finalize(
                    context, data["kg"], data["location"], data.get("photo_url"),
                    raw_message=data.get("raw_message", message),
                    source=data.get("source", "telegram"),
                    extra_data=data.get("extra_data"),
                    skip_duplicate_check=True,
                )
            if choice.startswith("b"):
                return self._correct_report(entry["existing_report_id"], data, context)
            pending_reports[telegram_id] = entry  # neither A nor B — ask again
            return "Balas A (tambahan baru) atau B (koreksi laporan tadi) ya 😊"

        # waiting_kg / waiting_location: parse the new message and merge
        kg, location = await self._parse_report(message)
        kg = kg if kg is not None else data.get("kg")
        location = location or data.get("location")
        photo_url = data.get("photo_url") or context.get("photo_url")

        if kg is None:
            _set_pending(
                telegram_id, "waiting_kg",
                {"kg": None, "location": location, "photo_url": photo_url},
            )
            return "Beratnya berapa kg ya? Contoh: '18 kg' ⚖️"
        if location is None:
            _set_pending(
                telegram_id, "waiting_location",
                {"kg": kg, "location": None, "photo_url": photo_url},
            )
            return f"Berat {kg:g} kg tercatat! Lokasinya di mana ya? 📍"

        return await self._finalize(
            context, kg, location, photo_url, raw_message=message,
            source=context.get("channel", "telegram"),
        )

    def _correct_report(self, report_id: str, data: dict, context: dict) -> str:
        update: dict = {"kg_collected": data["kg"], "location": data["location"]}
        if data.get("photo_url"):
            update["photo_url"] = data["photo_url"]
        db.table("reports").update(update).eq("id", report_id).execute()

        volunteer = context.get("volunteer") or {}
        mission = context.get("mission") or {}
        if volunteer.get("id") and mission.get("id"):
            self._sync_reported_kg(volunteer["id"], mission["id"])
        return (
            f"Laporan tadi sudah dikoreksi menjadi "
            f"{float(data['kg']):g} kg di {data['location']} ✅"
        )

    async def _parse_report(self, message: str) -> tuple[float | None, str | None]:
        """Step 1 — Claude Haiku extracts {kg, location} JSON from free-form text."""
        raw = await self.call_claude(
            PARSE_PROMPT, [{"role": "user", "content": f"Message: {message}"}],
            max_tokens=100,
        )
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("Report parse returned no JSON: %r", raw)
            return None, None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning("Report parse returned invalid JSON: %r", raw)
            return None, None
        kg = data.get("kg")
        location = data.get("location")
        return (float(kg) if kg is not None else None), (location or None)

    # --------------------------------------------------------------------- #
    # Part 3 — Google Form submission                                         #
    # --------------------------------------------------------------------- #

    async def process_form_submission(self, form_data: dict, context: dict) -> str:
        kg_str = _get_field(form_data, KG_FIELDS)
        location = _get_field(form_data, LOC_FIELDS)
        jenis = _get_field(form_data, TYPE_FIELDS)
        photo = _get_field(form_data, PHOTO_FIELDS)
        notes = _get_field(form_data, NOTES_FIELDS)

        try:
            kg = float(kg_str.replace(",", ".")) if kg_str else None
        except ValueError:
            kg = None

        volunteer = context.get("volunteer")
        name = volunteer["name"] if volunteer else "volunteer tidak dikenal"

        if kg is None or location is None:
            await _alert_fasilitator(
                f"⚠️ Form tidak lengkap dari {name}: kg={kg_str}, lokasi={location}"
            )
            return "Form tidak lengkap: berat (kg) dan lokasi wajib diisi."
        if volunteer is None:
            await _alert_fasilitator(
                f"⚠️ Form masuk tapi volunteer tidak ditemukan: {kg:g} kg - {location}"
            )
            return "Volunteer tidak ditemukan untuk form ini."

        photo_url = photo if photo and photo.startswith("http") else None
        if photo and not photo_url:
            logger.warning("Form photo field is not an accessible URL: %r", photo)

        raw_message = f"[Google Form] {kg:g} kg - {location}"
        if jenis:
            raw_message += f" - Jenis: {jenis}"
        if notes:
            raw_message += f" - Catatan: {notes}"

        extra_data = {
            key: value
            for key, value in (("jenis_plastik", jenis), ("catatan", notes)) if value
        }

        mission = context.get("mission") or self._get_active_mission(volunteer["id"])
        if mission is None:
            await _alert_fasilitator(
                f"⚠️ Form dari {name} tapi tidak ada misi aktif: {kg:g} kg - {location}"
            )
            return "Tidak ada misi aktif untuk volunteer ini."

        return await self.validate_and_save(
            volunteer, mission, kg, location, photo_url, raw_message,
            source="google_form", extra_data=extra_data,
        )

    # --------------------------------------------------------------------- #
    # Part 4 — validate and save (shared)                                     #
    # --------------------------------------------------------------------- #

    async def validate_and_save(
        self,
        volunteer: dict,
        mission: dict,
        kg: float,
        location: str,
        photo_url: str | None,
        raw_message: str,
        source: str,
        extra_data: dict | None = None,
        skip_duplicate_check: bool = False,
    ) -> str:
        # Check 1 — kg range
        if kg <= 0:
            return "Berat harus lebih dari 0 kg"
        if kg > 999:
            return "Berat terlalu besar, mohon periksa kembali"

        # Check 2 — quota threshold flag
        flag_reasons = []
        quota = float(mission.get("quota_kg") or volunteer.get("quota_kg") or 0)
        if quota and kg > quota * 2:
            flag_reasons.append(f"Berat {kg:g}kg melebihi 2x kuota ({quota:g}kg)")

        # Check 3 — location vs assigned area (substring match either way)
        assigned_area = (volunteer.get("area") or "").lower()
        reported_location = location.lower()
        if (
            assigned_area
            and assigned_area not in reported_location
            and reported_location not in assigned_area
        ):
            flag_reasons.append(
                f"Lokasi '{location}' di luar area tugas '{volunteer['area']}'"
            )

        # Check 4 — similar-weight duplicate today
        if not skip_duplicate_check:
            duplicate = self._find_duplicate_today(volunteer["id"], mission["id"], kg)
            if duplicate:
                _set_pending(
                    volunteer.get("telegram_id"),
                    "waiting_confirmation",
                    {
                        "kg": kg, "location": location, "photo_url": photo_url,
                        "raw_message": raw_message, "source": source,
                        "extra_data": extra_data,
                    },
                    existing_report_id=duplicate["id"],
                )
                return (
                    f"Kamu sudah pernah lapor {float(duplicate['kg_collected']):g} kg tadi.\n"
                    "Ini laporan tambahan atau koreksi? Balas:\n"
                    "A) Tambahan baru\n"
                    "B) Koreksi laporan tadi"
                )

        is_flagged = bool(flag_reasons)
        flag_reason = " | ".join(flag_reasons) if flag_reasons else None

        db.table("reports").insert(
            {
                "volunteer_id": volunteer["id"],
                "mission_id": mission["id"],
                "kg_collected": kg,
                "location": location,
                "photo_url": photo_url,
                "raw_message": raw_message,
                "source": source,
                "extra_data": extra_data or {},
                "is_flagged": is_flagged,
                "flag_reason": flag_reason,
                "verified": False,
            }
        ).execute()

        total_reported = self._sync_reported_kg(volunteer["id"], mission["id"])

        if is_flagged:
            await _alert_fasilitator(
                f"🚩 Laporan perlu dicek dari {volunteer['name']}:\n"
                f"📦 {kg:g} kg di {location} (via {source})\n"
                f"⚠️ Alasan: {flag_reason}\n"
                "Cek di dashboard → Reports → Perlu Dicek"
            )

        impact = ImpactCalculator.format_impact_summary(kg)
        remaining = max(quota - total_reported, 0)
        pct = (total_reported / quota * 100) if quota else 0

        if pct >= 100:
            status_line = "🎉 SELESAI! Kamu sudah memenuhi kuota misimu!"
        elif pct >= 75:
            status_line = f"Hampir selesai! Sisa {remaining:.1f} kg lagi 💪"
        elif pct >= 50:
            status_line = f"Sudah separuh jalan! Sisa {remaining:.1f} kg"
        else:
            status_line = f"Good start! Masih ada {remaining:.1f} kg lagi"

        confirmation = (
            f"✅ Laporan diterima, {volunteer['name']}!\n"
            f"📦 {kg:g} kg dari {location} tercatat.\n"
            f"📊 Progress: {total_reported:g}/{quota:g} kg ({pct:.0f}%) — {status_line}\n\n"
            f"🌍 Dampak hari ini:\n"
            f"  🍶 {impact['bottles']:,} botol diselamatkan\n"
            f"  🌿 {impact['co2_kg']:.1f} kg CO₂ dicegah"
        )
        if source == "google_form":
            confirmation += "\n\n📋 Laporan via form berhasil diterima!"
        return confirmation

    # --------------------------------------------------------------------- #
    # Part 6 — progress inquiry                                               #
    # --------------------------------------------------------------------- #

    async def process_progress_inquiry(self, context: dict) -> str:
        volunteer = context.get("volunteer")
        if volunteer is None and context.get("telegram_id"):
            volunteer = await self.get_volunteer(context["telegram_id"])
        if volunteer is None:
            return (
                "Kamu belum terdaftar sebagai volunteer. "
                "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
            )
        mission = context.get("mission") or self._get_active_mission(volunteer["id"])
        if mission is None:
            return (
                "Belum ada misi aktif yang diassign ke kamu. "
                "Fasilitator akan menginformasikan misi berikutnya ya 🙏"
            )

        personal_reports = (
            db.table("reports")
            .select("kg_collected, location, reported_at")
            .eq("volunteer_id", volunteer["id"])
            .eq("mission_id", mission["id"])
            .order("reported_at", desc=True)
            .execute()
            .data
            or []
        )
        personal_total = sum(float(r["kg_collected"]) for r in personal_reports)

        program_rows = (
            db.table("reports")
            .select("kg_collected")
            .eq("mission_id", mission["id"])
            .neq("verified", False)
            .execute()
            .data
            or []
        )
        program_total = sum(float(r["kg_collected"]) for r in program_rows)

        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        today_rows = (
            db.table("reports")
            .select("volunteer_id")
            .eq("mission_id", mission["id"])
            .gte("reported_at", today_start)
            .execute()
            .data
            or []
        )
        today_count = len({r["volunteer_id"] for r in today_rows})

        assignments = (
            db.table("volunteer_missions")
            .select("quota_kg")
            .eq("mission_id", mission["id"])
            .execute()
            .data
            or []
        )
        target = sum(float(a["quota_kg"] or 0) for a in assignments)

        quota = float(mission.get("quota_kg") or volunteer.get("quota_kg") or 0)
        pct = (personal_total / quota * 100) if quota else 0

        report_lines = [
            f"• {r['reported_at'][:10]}: {float(r['kg_collected']):g} kg di {r['location']}"
            for r in personal_reports[:3]
        ]
        recent = "\n".join(report_lines) if report_lines else "• belum ada laporan"

        return (
            f"📊 Progress kamu, {volunteer['name']}:\n"
            f"📦 Total: {personal_total:g}/{quota:g} kg ({pct:.0f}%)\n"
            f"📅 Laporan: {len(personal_reports)} kali\n\n"
            f"Laporan terakhir:\n{recent}\n\n"
            f"🌍 Program keseluruhan: {program_total:g} kg dari {target:g} kg\n"
            f"👥 {today_count} volunteer lapor hari ini"
        )

    # --------------------------------------------------------------------- #
    # Shared DB helpers                                                       #
    # --------------------------------------------------------------------- #

    async def _finalize(
        self,
        context: dict,
        kg: float,
        location: str,
        photo_url: str | None,
        raw_message: str,
        source: str,
        extra_data: dict | None = None,
        skip_duplicate_check: bool = False,
    ) -> str:
        """Resolve volunteer + mission from context, then validate_and_save."""
        volunteer = context.get("volunteer")
        if volunteer is None and context.get("telegram_id"):
            volunteer = await self.get_volunteer(context["telegram_id"])
        if volunteer is None:
            return (
                "Kamu belum terdaftar sebagai volunteer. "
                "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
            )
        mission = context.get("mission") or self._get_active_mission(volunteer["id"])
        if mission is None:
            return (
                "Belum ada misi aktif, jadi laporanmu belum bisa dicatat. "
                "Hubungi fasilitator ya 🙏"
            )
        return await self.validate_and_save(
            volunteer, mission, kg, location, photo_url, raw_message,
            source, extra_data, skip_duplicate_check,
        )

    async def _program_summary(self, context: dict) -> str:
        """Fasilitator-persona view: program-wide totals + who's behind on quota."""
        missions = (
            db.table("missions").select("*").eq("status", "active").execute().data
            or []
        )
        if not missions:
            return "Belum ada misi aktif. Tidak ada progress untuk dirangkum."

        chunks: list[str] = []
        for mission in missions:
            assignments = (
                db.table("volunteer_missions")
                .select(
                    "quota_kg, reported_kg, assigned_area, volunteers(name)"
                )
                .eq("mission_id", mission["id"])
                .execute()
                .data
                or []
            )
            total_quota = sum(float(a.get("quota_kg") or 0) for a in assignments)
            total_reported = sum(float(a.get("reported_kg") or 0) for a in assignments)
            pct = (total_reported / total_quota * 100) if total_quota else 0

            behind: list[dict] = []
            for assignment in assignments:
                quota = float(assignment.get("quota_kg") or 0)
                reported = float(assignment.get("reported_kg") or 0)
                if quota > 0 and reported / quota < 0.5:
                    behind.append(assignment)

            lines = [
                f"📊 *{mission.get('title')}*",
                f"Progress program: {total_reported:g}/{total_quota:g} kg ({pct:.1f}%)",
                f"Volunteer ter-assign: {len(assignments)}",
                f"Tertinggal (<50% kuota): {len(behind)}",
            ]
            if behind:
                names = [
                    (a.get("volunteers") or {}).get("name", "?") for a in behind[:10]
                ]
                lines.append("Yang tertinggal: " + ", ".join(names))
            chunks.append("\n".join(lines))

        return "\n\n".join(chunks)

    @staticmethod
    def _get_active_mission(volunteer_id: str) -> dict | None:
        result = (
            db.table("volunteer_missions")
            .select("quota_kg, assigned_area, missions(*)")
            .eq("volunteer_id", volunteer_id)
            .execute()
        )
        for row in result.data or []:
            mission = row.get("missions")
            if mission and mission.get("status") == "active":
                mission["quota_kg"] = row.get("quota_kg")
                mission["assigned_area"] = row.get("assigned_area")
                return mission
        return None

    @staticmethod
    def _find_duplicate_today(volunteer_id: str, mission_id: str, kg: float) -> dict | None:
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        rows = (
            db.table("reports")
            .select("id, kg_collected")
            .eq("volunteer_id", volunteer_id)
            .eq("mission_id", mission_id)
            .gte("reported_at", today_start)
            .execute()
            .data
            or []
        )
        return next(
            (r for r in rows if abs(float(r["kg_collected"]) - kg) < 1), None
        )

    @staticmethod
    def _sync_reported_kg(volunteer_id: str, mission_id: str) -> float:
        """Recompute the volunteer's total for this mission and mirror it on volunteer_missions."""
        rows = (
            db.table("reports")
            .select("kg_collected")
            .eq("volunteer_id", volunteer_id)
            .eq("mission_id", mission_id)
            .execute()
            .data
            or []
        )
        total = sum(float(r["kg_collected"]) for r in rows)
        try:
            (
                db.table("volunteer_missions")
                .update({"reported_kg": total})
                .eq("volunteer_id", volunteer_id)
                .eq("mission_id", mission_id)
                .execute()
            )
        except Exception as exc:
            # Column requires the Part-7 migration; don't fail the report if it's missing
            logger.warning("Could not update volunteer_missions.reported_kg: %s", exc)
        return total
