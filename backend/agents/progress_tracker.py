"""Progress tracker agent: parses collection reports (chat + Google Form) and answers progress queries.

The orchestration logic lives here; the heavier-weight pieces have been
broken out into dedicated services so this file can read top-to-bottom:

* ``services/pending_state`` — multi-turn in-memory state with TTL.
* ``services/notifications`` — Telegram / WhatsApp DM helpers.
* ``services/report_repository`` — Supabase reads/writes for ``reports``.

The legacy module-level symbols (``pending_reports``, ``_alert_fasilitator``,
``cleanup_expired_pending``, ...) are re-exported below so external imports
(``main.py``, the router, the tests) keep working unchanged.
"""

import json
import logging
import re
from datetime import datetime, timezone

from backend.database.supabase_client import db
from backend.utils.date_utils import format_hhmm as _shared_format_hhmm
from backend.utils.impact_calculator import ImpactCalculator
from backend.utils.photo_verifier import PhotoVerifier
from backend.utils.query_utils import get_active_mission as _shared_get_active_mission

from .base_agent import BaseAgent
from .intent_registry import register_intent
from .prompts.progress_tracker import PARSE_PROMPT
from .services import pending_state, report_repository
from .services.notifications import alert_fasilitator, notify_volunteer

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------- #
# Pending state — re-exports for back-compat with main.py / router / tests.  #
# ------------------------------------------------------------------------- #

PendingKey = pending_state.PendingKey
PENDING_TTL = pending_state.PENDING_TTL
pending_reports = pending_state.store
_pending_key = pending_state.pending_key
_set_pending = pending_state.set_pending
has_pending_report = pending_state.has_pending
has_pending_report_for_context = pending_state.has_pending_for_context
cleanup_expired_pending = pending_state.cleanup_expired

# Notification helpers re-exported (main.py patches/uses these names).
_alert_fasilitator = alert_fasilitator
_notify_volunteer = notify_volunteer

INQUIRY_KEYWORDS = (
    "berapa", "sudah berapa", "progress", "total", "sisa",
    "kuota", "pencapaian", "sudah sampai mana",
    "peringkat", "ranking", "rank", "leaderboard",
)

RANK_KEYWORDS = ("peringkat", "ranking", "rank", "leaderboard")

# Keyword sets for the duplicate-clarification multi-turn flow.
NEW_REPORT_KEYWORDS = ("tambahan", "baru", "berbeda", "lain", "tambah")
CORRECTION_KEYWORDS = ("sama", "koreksi", "salah", "ganti", "perbaiki", "betulkan")

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


def _get_field(data: dict, candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        if key in data and data[key]:
            return str(data[key]).strip()
    return None


@register_intent(
    name="progress_tracker",
    description=(
        "laporan plastik terkumpul (mengandung angka + kg/kilo + lokasi), "
        "pertanyaan tentang progress atau sisa target pribadi"
    ),
    examples=(
        "laporan 18 kg menteng",
        "udah nih 25 kilo di cikini [foto]",
        "saya sudah kumpul 5 kg di senen",
        "laporan foto",
        "progress saya udah berapa kg?",
        "kurang berapa lagi biar capai target?",
    ),
)
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
        if has_pending_report_for_context(context):
            reply = await self._resume_pending(message, context)
        elif any(kw in message.lower() for kw in RANK_KEYWORDS):
            reply = await self.process_rank_inquiry(context)
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
        key = _pending_key(context)
        photo_url = context.get("photo_url")
        kg, location = await self._parse_report(message)

        if kg is None and photo_url:
            _set_pending(
                key,
                "waiting_kg",
                {"kg": None, "location": location, "photo_url": photo_url},
            )
            return ASK_KG_AND_LOCATION_MSG
        if kg is None:
            return ASK_FORMAT_MSG
        if location is None:
            _set_pending(
                key,
                "waiting_location",
                {"kg": kg, "location": None, "photo_url": photo_url},
            )
            return f"Berat {kg:g} kg tercatat! Lokasinya di mana ya? 📍"

        return await self._finalize(
            context, kg, location, photo_url, raw_message=message,
            source=context.get("source") or context.get("channel", "telegram"),
        )

    async def _resume_pending(self, message: str, context: dict) -> str:
        """Part 5 — complete (or correct) a report using the saved pending state."""
        key = _pending_key(context)
        entry = pending_reports.pop(key)
        data = entry["data"]

        if entry["step"] == "waiting_confirmation":
            choice = message.strip().lower()
            if any(kw in choice for kw in NEW_REPORT_KEYWORDS):
                confirmation = await self._finalize(
                    context, data["kg"], data["location"], data.get("photo_url"),
                    raw_message=data.get("raw_message", message),
                    source=data.get("source", "telegram"),
                    extra_data=data.get("extra_data"),
                    skip_duplicate_check=True,
                )
                volunteer = context.get("volunteer") or {}
                mission = context.get("mission") or {}
                total = (
                    self._sync_reported_kg(volunteer["id"], mission["id"])
                    if volunteer.get("id") and mission.get("id")
                    else 0
                )
                return f"✅ Ditambahkan! Total sekarang {total:g} kg\n\n" + confirmation
            if any(kw in choice for kw in CORRECTION_KEYWORDS):
                return self._correct_report(entry["existing_report_id"], data, context)
            # Neither keyword family matched — restore state and ask again
            # with explicit instructions.
            pending_reports[key] = entry
            return (
                "Maaf, bisa diperjelas? Ketik 'tambahan' kalau ini laporan baru, "
                "atau 'koreksi' kalau mau ganti laporan tadi."
            )

        # waiting_kg / waiting_location: parse the new message and merge
        kg, location = await self._parse_report(message)
        kg = kg if kg is not None else data.get("kg")
        location = location or data.get("location")
        photo_url = data.get("photo_url") or context.get("photo_url")

        if kg is None:
            _set_pending(
                key, "waiting_kg",
                {"kg": None, "location": location, "photo_url": photo_url},
            )
            return "Beratnya berapa kg ya? Contoh: '18 kg' ⚖️"
        if location is None:
            _set_pending(
                key, "waiting_location",
                {"kg": kg, "location": None, "photo_url": photo_url},
            )
            return f"Berat {kg:g} kg tercatat! Lokasinya di mana ya? 📍"

        return await self._finalize(
            context, kg, location, photo_url, raw_message=message,
            source=context.get("source") or context.get("channel", "telegram"),
        )

    def _correct_report(self, report_id: str, data: dict, context: dict) -> str:
        old_kg = data.get("existing_kg")
        update: dict = {"kg_collected": data["kg"], "location": data["location"]}
        if data.get("photo_url"):
            update["photo_url"] = data["photo_url"]
        report_repository.update_report(report_id, update)

        volunteer = context.get("volunteer") or {}
        mission = context.get("mission") or {}
        if volunteer.get("id") and mission.get("id"):
            self._sync_reported_kg(volunteer["id"], mission["id"])
        if old_kg is not None:
            return (
                f"✅ Laporan dikoreksi dari {float(old_kg):g} kg "
                f"menjadi {float(data['kg']):g} kg"
            )
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
            source="google_form", extra_data=extra_data, context=context,
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
        context: dict | None = None,
    ) -> str:
        # Check 1 — kg range
        if kg <= 0:
            return "Berat harus lebih dari 0 kg"
        if kg > 999:
            return "Berat terlalu besar, mohon periksa kembali"

        # Check 2 — quota threshold flag
        flag_reasons: list[str] = []
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

        # Check 4 — multi-turn duplicate clarification (3-tier classifier)
        if not skip_duplicate_check:
            existing = self._find_latest_today(volunteer["id"], mission["id"])
            if existing is not None:
                verdict, ask_message = self._classify_duplicate(existing, kg, location)
                if verdict in {"clear_duplicate", "ambiguous"}:
                    pending_key = _pending_key(context) or volunteer.get("telegram_id")
                    _set_pending(
                        pending_key,
                        "waiting_confirmation",
                        {
                            "kg": kg, "location": location, "photo_url": photo_url,
                            "raw_message": raw_message, "source": source,
                            "extra_data": extra_data,
                            "existing_kg": float(existing["kg_collected"]),
                        },
                        existing_report_id=existing["id"],
                    )
                    return ask_message
                # likely_addition → fall through and save normally

        # Check 5 — vision-based photo verification
        is_relay = source == "fasilitator_relay"
        verifier = PhotoVerifier()
        photo_result = await verifier.verify_or_skip(
            photo_url=photo_url,
            reported_kg=kg,
            volunteer_area=volunteer.get("area") or "",
            is_fasilitator_relay=is_relay,
            require_photo=True,
        )

        # 5a. No photo and one is required → ask sender to retry
        if photo_result.get("needs_photo"):
            return photo_result["message"]

        # 5b. Photo clearly does not show plastic → reject without saving
        if photo_result.get("verdict") == "fail":
            return (
                f"Hai {volunteer.get('name', '')}! "
                "Foto yang dikirim sepertinya bukan foto plastik. "
                f"{photo_result.get('reason_id', '')}\n\n"
                "Boleh kirim ulang foto plastik + timbangan ya? 📸"
            )

        # 5c. Suspect photo → save but flag
        if photo_result.get("should_flag"):
            photo_flag = photo_result.get("flag_reason")
            if photo_flag:
                flag_reasons.append(photo_flag)

        is_flagged = bool(flag_reasons)
        flag_reason = " | ".join(flag_reasons) if flag_reasons else None

        # Fasilitator-relayed reports are pre-verified by the fasilitator.
        verified = is_relay

        # Stamp per-channel test mode so dashboards can filter out forensic data.
        is_test = bool((context or {}).get("is_test_mode"))

        report_extra = dict(extra_data or {})
        report_extra["photo_verification"] = photo_result

        report_repository.insert_report(
            {
                "volunteer_id": volunteer["id"],
                "mission_id": mission["id"],
                "kg_collected": kg,
                "location": location,
                "photo_url": photo_url,
                "raw_message": raw_message,
                "source": source,
                "extra_data": report_extra,
                "is_flagged": is_flagged,
                "flag_reason": flag_reason,
                "verified": verified,
                "is_test": is_test,
            }
        )

        total_reported = report_repository.sync_reported_kg(volunteer["id"], mission["id"])

        # Fire-and-forget impact-score recompute so the reply isn't blocked.
        try:
            import asyncio

            from backend.utils.ranking_calculator import RankingCalculator

            asyncio.create_task(RankingCalculator().refresh_volunteer(volunteer["id"]))
        except Exception as exc:
            logger.warning("Could not schedule rank refresh for %s: %s", volunteer["id"], exc)

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
        if is_relay:
            confirmation += "\n\n✅ Diverifikasi fasilitator."
            # Also DM the target volunteer so they see the credit landing.
            await _notify_volunteer(
                volunteer,
                f"📨 Fasilitator mencatat laporan kamu: {kg:g} kg di {location}.\n"
                f"Status: terverifikasi.\n"
                f"Progress: {total_reported:g}/{quota:g} kg ({pct:.0f}%)",
            )
        return confirmation

    # --------------------------------------------------------------------- #
    # Part 6 — progress inquiry                                               #
    # --------------------------------------------------------------------- #

    async def process_rank_inquiry(self, context: dict) -> str:
        """Personal rank line ('Kamu di peringkat ke-7 dari 50 volunteer! 🏆')."""
        from backend.utils.ranking_calculator import RankingCalculator

        volunteer = context.get("volunteer") or await self.get_volunteer_flexible(context)
        if volunteer is None:
            return (
                "Kamu belum terdaftar sebagai volunteer. "
                "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
            )

        calc = RankingCalculator()
        # Ensure the volunteer's own score is fresh — cheap enough inline.
        await calc.refresh_volunteer(volunteer["id"])
        info = await calc.get_personal_rank(volunteer["id"])
        if info is None or not info.get("rank"):
            return (
                "Peringkat kamu belum tersedia. Tunggu update ranking malam ini "
                "ya — biasanya jam 23:00 🤝"
            )

        lines = [
            f"Kamu di peringkat ke-{info['rank']} dari {info['total_count']} volunteer! 🏆",
            f"Skor total: {info['total_score']:g} "
            f"(impact: {info['kg_collected']:g} kg, "
            f"quiz: {info['quiz_correct_count']} benar)",
        ]
        if info.get("ahead_name"):
            lines.append(f"Kamu hampir menyusul {info['ahead_name']} di peringkat {info['rank'] - 1}!")
        return "\n".join(lines)

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
            source, extra_data, skip_duplicate_check, context=context,
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

    _get_active_mission = staticmethod(_shared_get_active_mission)

    _find_duplicate_today = staticmethod(report_repository.find_duplicate_today)
    _find_latest_today = staticmethod(report_repository.find_latest_today)

    @staticmethod
    def _classify_duplicate(
        existing: dict, new_kg: float, new_location: str
    ) -> tuple[str, str]:
        """Return ``(verdict, ask_message)`` for the duplicate clarifier.

        Verdicts:
        * ``clear_duplicate`` — kg within 1, same location.
        * ``ambiguous``      — kg 1..5 apart.
        * ``likely_addition`` — kg ≥ 5 apart or different location.

        ``ask_message`` is only meaningful for the first two verdicts.
        """
        existing_kg = float(existing.get("kg_collected") or 0)
        existing_loc = (existing.get("location") or "")
        kg_diff = abs(new_kg - existing_kg)
        same_location = (
            new_location.lower() in existing_loc.lower()
            or existing_loc.lower() in new_location.lower()
        )
        time_str = ProgressTrackerAgent._format_local_time(existing.get("reported_at"))

        if kg_diff < 1 and same_location:
            ask = (
                f"Kamu tadi sudah submit {existing_kg:g} kg dari {existing_loc} "
                f"pada pukul {time_str}. Ini laporan tambahan atau sama?"
            )
            return "clear_duplicate", ask

        if kg_diff >= 5 or not same_location:
            return "likely_addition", ""

        ask = (
            f"Tadi kamu sudah lapor {existing_kg:g} kg pada {time_str}. "
            f"Laporan baru ini {new_kg:g} kg — ini tambahan atau koreksi "
            "laporan tadi?"
        )
        return "ambiguous", ask

    _format_local_time = staticmethod(_shared_format_hhmm)

    _sync_reported_kg = staticmethod(report_repository.sync_reported_kg)
