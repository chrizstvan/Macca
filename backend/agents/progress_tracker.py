"""Progress tracker agent: parses collection reports (chat + Google Form) and answers progress queries.

The orchestration logic lives here; the heavier-weight pieces have been
broken out into dedicated services so this file can read top-to-bottom:

* ``services/pending_state`` — multi-turn in-memory state with TTL.
* ``services/notifications`` — Telegram / WhatsApp DM helpers.

The legacy module-level symbols (``pending_reports``, ``_alert_fasilitator``,
``cleanup_expired_pending``, ...) are re-exported below so external imports
(``main.py``, the router, the tests) keep working unchanged.
"""

import json
import logging
import re
from datetime import datetime, timezone

from backend.agents.services.reporting_flag import (
    is_reporting_enabled,
    reporting_off_message,
)
from backend.utils.date_utils import format_hhmm as _shared_format_hhmm
from backend.utils.impact_calculator import ImpactCalculator
from backend.utils.query_utils import get_active_mission as _shared_get_active_mission

from .base_agent import BaseAgent
from .intent_registry import register_intent
from .prompts.progress_tracker import PARSE_PROMPT
from .services import pending_state
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

# Program is challenge-based now — per-kg progress + points/ranking are not
# tracked by the bot. Inquiry replies point volunteers to the challenge instead.
_CHALLENGE_FOCUS_MSG = (
    "Yuk fokus ke <b>challenge</b> yang sedang aktif 🌱 Mau tahu tahapan atau "
    "cara ikutnya? Tanya aku aja! Kalau soal nilai/poin, itu diurus panitia "
    "lewat Google Form ya 😊"
)

# Keyword sets for the duplicate-clarification multi-turn flow.
NEW_REPORT_KEYWORDS = ("tambahan", "baru", "berbeda", "lain", "tambah")
CORRECTION_KEYWORDS = ("sama", "koreksi", "salah", "ganti", "perbaiki", "betulkan")

KG_FIELDS = ("Berat Plastik (kg)", "Berat (kg)", "Kg", "Berat")
LOC_FIELDS = ("Lokasi Pengumpulan", "Lokasi", "Area", "Kelurahan")
TYPE_FIELDS = ("Jenis Plastik", "Tipe Plastik", "Jenis")
PHOTO_FIELDS = ("Foto", "Upload Foto", "Dokumentasi")
NOTES_FIELDS = ("Catatan", "Keterangan", "Notes")

ASK_FORMAT_MSG = (
    "Boleh input laporannya dengan format:\n"
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
        is_report_path = has_pending_report_for_context(context) or not (
            any(kw in message.lower() for kw in RANK_KEYWORDS)
            or self.is_progress_inquiry(message)
        )
        if is_report_path and not await is_reporting_enabled():
            # Feature flag off — block volunteer reporting (new + in-flight).
            # Inquiries above and Google Form (handled earlier) stay available.
            reply = await reporting_off_message()
        elif has_pending_report_for_context(context):
            reply = await self._resume_pending(message, context)
        elif any(kw in message.lower() for kw in RANK_KEYWORDS):
            reply = _CHALLENGE_FOCUS_MSG
        elif self.is_progress_inquiry(message):
            reply = _CHALLENGE_FOCUS_MSG
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
                mission = context.get("mission") or (
                    self._get_active_mission(volunteer["id"])
                    if volunteer.get("id")
                    else None
                ) or {}
                total = (
                    await self._sync_reported_kg(volunteer["id"], mission["id"])
                    if volunteer.get("id") and mission.get("id")
                    else 0
                )
                return f"✅ Ditambahkan! Total sekarang {total:g} kg\n\n" + confirmation
            if any(kw in choice for kw in CORRECTION_KEYWORDS):
                return await self._correct_report(entry["existing_report_id"], data, context)
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

    async def _correct_report(self, report_id: str, data: dict, context: dict) -> str:
        from uuid import UUID

        from backend.domain.value_objects.kg import Kg
        from backend.infrastructure.composition_root import (
            build_report_repository,
        )

        old_kg = data.get("existing_kg")
        await build_report_repository().update(
            UUID(str(report_id)),
            kg=Kg(float(data["kg"])),
            location=data["location"],
            photo_url=data.get("photo_url"),
        )

        volunteer = context.get("volunteer") or {}
        mission = context.get("mission") or (
            self._get_active_mission(volunteer["id"])
            if volunteer.get("id")
            else None
        ) or {}
        if volunteer.get("id") and mission.get("id"):
            await self._sync_reported_kg(volunteer["id"], mission["id"])
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

        # Form submissions go through the same use case as chat reports.
        # context["volunteer"]/["mission"] are already populated above so
        # ``_finalize`` won't re-fetch them.
        context["volunteer"] = volunteer
        context["mission"] = mission
        return await self._finalize(
            context,
            kg,
            location,
            photo_url,
            raw_message=raw_message,
            source="google_form",
            extra_data=extra_data,
        )

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
                "Yuk ikut challenge yang sedang aktif 🌱 "
                "Tanya aku soal tahapan atau cara ikutnya ya!"
            )

        from uuid import UUID

        from backend.infrastructure.composition_root import (
            build_mission_repository,
            build_report_repository,
        )

        reports_repo = build_report_repository()
        missions_repo = build_mission_repository()
        vol_uuid = UUID(str(volunteer["id"]))
        mission_uuid = UUID(str(mission["id"]))

        personal_reports = await reports_repo.list_for_volunteer_in_mission(
            vol_uuid, mission_uuid
        )
        personal_total = sum(r.kg_collected.value for r in personal_reports)

        program_total = await reports_repo.program_total_kg(mission_uuid)
        today_count = await reports_repo.count_reporters_today(mission_uuid)
        target = await missions_repo.assignment_quota_total(mission_uuid)

        quota = float(mission.get("quota_kg") or volunteer.get("quota_kg") or 0)
        pct = (personal_total / quota * 100) if quota else 0

        report_lines = [
            f"• {r.reported_at.date().isoformat() if r.reported_at else '-'}: "
            f"{r.kg_collected.value:g} kg di {r.location}"
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
        """Resolve volunteer + mission from context, then route via SubmitReport."""
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
                "Yuk ikut challenge yang sedang aktif 🌱 "
                "Tanya aku soal tahapan atau cara ikutnya ya!"
            )

        return await self._submit_via_use_case(
            context=context,
            volunteer=volunteer,
            mission=mission,
            kg=kg,
            location=location,
            photo_url=photo_url,
            raw_message=raw_message,
            source=source,
            extra_data=extra_data,
            skip_duplicate_check=skip_duplicate_check,
        )

    # ------------------------------------------------------------------ #
    # SubmitReport use-case bridge                                        #
    # ------------------------------------------------------------------ #

    async def _submit_via_use_case(
        self,
        *,
        context: dict,
        volunteer: dict,
        mission: dict,
        kg: float,
        location: str,
        photo_url: str | None,
        raw_message: str,
        source: str,
        extra_data: dict | None,
        skip_duplicate_check: bool,
    ) -> str:
        """Route the save through the SubmitReport use case + translate outcome."""
        # Lazy import keeps composition root out of the agent's startup path.
        from uuid import UUID

        from backend.application.use_cases.submit_report import (
            DuplicateClarificationNeeded,
            NeedsPhoto,
            PhotoRejected,
            Saved,
        )
        from backend.domain.errors import InvalidKg
        from backend.infrastructure.composition_root import build_submit_report

        use_case = build_submit_report()
        try:
            outcome = await use_case.execute(
                volunteer_id=UUID(str(volunteer["id"])),
                kg_value=kg,
                location=location,
                source=source,
                photo_url=photo_url,
                is_test=bool((context or {}).get("is_test_mode")),
                skip_duplicate_check=skip_duplicate_check,
                extra_data=extra_data,
            )
        except InvalidKg as exc:
            return str(exc)

        if isinstance(outcome, NeedsPhoto):
            # Park pending state so the next inbound (the photo) routes back
            # here instead of being classified by the router as a fresh
            # message (without state, "laporan foto" would otherwise be
            # treated as a cross-volunteer query).
            _set_pending(
                _pending_key(context),
                "waiting_photo",
                {
                    "kg": kg,
                    "location": location,
                    "photo_url": None,
                    "raw_message": raw_message,
                    "source": source,
                    "extra_data": extra_data,
                },
            )
            return outcome.message

        if isinstance(outcome, PhotoRejected):
            return (
                f"Hai {volunteer.get('name', '')}! "
                "Foto yang dikirim sepertinya bukan foto plastik. "
                f"{outcome.reason}\n\n"
                "Boleh kirim ulang foto plastik + timbangan ya? 📸"
            )

        if isinstance(outcome, DuplicateClarificationNeeded):
            return self._handle_duplicate_clarification(
                outcome=outcome,
                kg=kg,
                location=location,
                photo_url=photo_url,
                raw_message=raw_message,
                source=source,
                extra_data=extra_data,
                context=context,
            )

        assert isinstance(outcome, Saved)
        return await self._after_save(
            saved=outcome,
            volunteer=volunteer,
            mission=mission,
            source=source,
        )

    def _handle_duplicate_clarification(
        self,
        *,
        outcome,
        kg: float,
        location: str,
        photo_url: str | None,
        raw_message: str,
        source: str,
        extra_data: dict | None,
        context: dict,
    ) -> str:
        """Park pending state + render the spec-exact ask message."""
        existing = outcome.existing
        existing_kg = existing.kg_collected.value
        existing_loc = existing.location
        time_str = self._format_local_time(
            existing.reported_at.isoformat() if existing.reported_at else None
        )

        if outcome.verdict.value == "clear_duplicate":
            ask = (
                f"Kamu tadi sudah submit {existing_kg:g} kg dari "
                f"{existing_loc} pada pukul {time_str}. "
                "Ini laporan tambahan atau sama?"
            )
        else:
            ask = (
                f"Tadi kamu sudah lapor {existing_kg:g} kg pada {time_str}. "
                f"Laporan baru ini {kg:g} kg — ini tambahan atau koreksi "
                "laporan tadi?"
            )

        pending_key = _pending_key(context) or (
            (context.get("volunteer") or {}).get("telegram_id")
        )
        _set_pending(
            pending_key,
            "waiting_confirmation",
            {
                "kg": kg,
                "location": location,
                "photo_url": photo_url,
                "raw_message": raw_message,
                "source": source,
                "extra_data": extra_data,
                "existing_kg": existing_kg,
            },
            existing_report_id=str(existing.id),
        )
        return ask

    async def _after_save(
        self,
        *,
        saved,
        volunteer: dict,
        mission: dict,
        source: str,
    ) -> str:
        """Post-save side effects + confirmation text (matches legacy format)."""
        import asyncio as _asyncio

        report = saved.report
        total_reported = saved.total_kg
        quota = float(mission.get("quota_kg") or volunteer.get("quota_kg") or 0)

        # Fasilitator alert on flagged reports
        if report.is_flagged:
            await _alert_fasilitator(
                f"🚩 Laporan perlu dicek dari {volunteer.get('name', '')}:\n"
                f"📦 {report.kg_collected.value:g} kg di {report.location} "
                f"(via {source})\n"
                f"⚠️ Alasan: {report.flag_reason}\n"
                "Cek di dashboard → Reports → Perlu Dicek"
            )

        # Fire-and-forget rank refresh
        try:
            from backend.utils.ranking_calculator import RankingCalculator

            _asyncio.create_task(
                RankingCalculator().refresh_volunteer(str(report.volunteer_id))
            )
        except Exception as exc:
            logger.warning("Could not schedule rank refresh: %s", exc)

        impact = ImpactCalculator.format_impact_summary(report.kg_collected.value)
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
            f"✅ Laporan diterima, {volunteer.get('name', '')}! "
            f"{report.kg_collected.value:g} kg dari {report.location} tercatat.\n\n"
            "📊 Dampak laporan kamu hari ini:\n"
            f"  🍶 {impact['bottles']:,} botol plastik diselamatkan dari lautan\n"
            f"  🌿 {impact['co2_kg']:.1f} kg emisi CO₂ dicegah\n\n"
            f"Progress total: {total_reported:g}/{quota:g} kg ({pct:.0f}%)\n"
            f"{status_line}"
        )

        # Team mode — append rollup so volunteer sees the team total too.
        team_line = await self._team_progress_line(
            volunteer=volunteer, mission_id=report.mission_id
        )
        if team_line:
            confirmation += "\n\n" + team_line
        if source == "google_form":
            confirmation += "\n\n📋 Laporan via form berhasil diterima!"
        if source == "fasilitator_relay":
            confirmation += "\n\n✅ Diverifikasi fasilitator."
            await _notify_volunteer(
                volunteer,
                f"📨 Fasilitator mencatat laporan kamu: "
                f"{report.kg_collected.value:g} kg di {report.location}.\n"
                f"Status: terverifikasi.\n"
                f"Progress: {total_reported:g}/{quota:g} kg ({pct:.0f}%)",
            )
        return confirmation

    async def _team_progress_line(
        self, *, volunteer: dict, mission_id
    ) -> str:
        """Render the team rollup line for ``volunteer`` if they are in a team.

        Returns an empty string when the volunteer has no ``team`` set
        (individual mission) — the caller can append unconditionally.
        """
        team = volunteer.get("team")
        # Tolerate both ``text[]`` (legacy) and plain ``text`` columns.
        if isinstance(team, list):
            team = next((t for t in team if t and str(t).strip()), None)
        if not team or not str(team).strip():
            return ""

        try:
            from uuid import UUID

            from backend.infrastructure.composition_root import build_team_repository

            progress = await build_team_repository().get_progress(
                team=str(team).strip(),
                mission_id=mission_id if hasattr(mission_id, "hex") else UUID(str(mission_id)),
            )
        except Exception as exc:
            logger.warning("team progress lookup failed: %s", exc)
            return ""

        if progress.member_count == 0:
            return ""
        return (
            f"👥 Tim **{progress.team}** "
            f"({progress.member_count} anggota): "
            f"{progress.reported_kg:g}/{progress.total_quota_kg:g} kg "
            f"({progress.pct:.0f}%)"
        )

    async def _program_summary(self, context: dict) -> str:
        """Fasilitator-persona view: program-wide totals + who's behind on quota."""
        from backend.infrastructure.composition_root import (
            build_mission_repository,
        )

        missions_repo = build_mission_repository()
        missions = await missions_repo.list_active()
        if not missions:
            return "Belum ada misi aktif. Tidak ada progress untuk dirangkum."

        chunks: list[str] = []
        for mission in missions:
            assignments = await missions_repo.list_assignments_with_names(
                mission.id
            )
            total_quota = sum(a["quota_kg"] for a in assignments)
            total_reported = sum(a["reported_kg"] for a in assignments)
            pct = (total_reported / total_quota * 100) if total_quota else 0

            behind = [
                a
                for a in assignments
                if a["quota_kg"] > 0 and a["reported_kg"] / a["quota_kg"] < 0.5
            ]

            lines = [
                f"📊 *{mission.title}*",
                f"Progress program: {total_reported:g}/{total_quota:g} kg ({pct:.1f}%)",
                f"Volunteer ter-assign: {len(assignments)}",
                f"Tertinggal (<50% kuota): {len(behind)}",
            ]
            if behind:
                names = [a["name"] for a in behind[:10]]
                lines.append("Yang tertinggal: " + ", ".join(names))
            chunks.append("\n".join(lines))

        return "\n\n".join(chunks)

    _get_active_mission = staticmethod(_shared_get_active_mission)

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

    async def _sync_reported_kg(self, volunteer_id, mission_id) -> float:
        """Recompute the volunteer's mission total and mirror it onto
        ``volunteer_missions.reported_kg``. Returns the new total."""
        from uuid import UUID

        from backend.infrastructure.composition_root import (
            build_mission_repository,
            build_report_repository,
        )

        vid = UUID(str(volunteer_id))
        mid = UUID(str(mission_id))
        total = await build_report_repository().total_kg_for(vid, mid)
        await build_mission_repository().update_reported_kg(
            volunteer_id=vid, mission_id=mid, total_kg=total
        )
        return total
