"""Volunteer Support Agent — emotional support + plastic education.

Two roles in one agent:

1. **Emotional support** — motivate, handle complaints, escalate crisis.
2. **Plastic education** — answer questions about plastic types,
   environmental impact, recycling, alternatives, and how to educate the
   community.

Pipeline:

* A cheap keyword topic gate fronts every call so clearly off-topic
  messages never hit the LLM.
* The on-topic path classifies the *situation* with Claude Haiku
  (max 5 tokens) so the response prompt can route accordingly.
* The reply itself runs on Claude Sonnet for empathy + nuance.
* ``want_to_quit`` triggers an ``[ESCALATE]`` tag (stripped before sending
  to the volunteer) and a Telegram-style alert to the fasilitator.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .base_agent import BaseAgent, COMPLEX_MODEL, DEFAULT_MODEL
from .intent_registry import register_intent
from .prompts.volunteer_support import (
    CLASSIFY_PROMPT,
    SYSTEM_PROMPT,  # back-compat alias for header-only prompt
    build_system_prompt,
)
from .services.notifications import alert_fasilitator

ALLOWED_TOPICS = (
    "program", "misi", "tugas", "challenge",
    "plastik", "daur ulang", "lingkungan", "sampah",
    "karbon", "co2", "jejak karbon", "emisi",
    "submit", "laporan", "progress", "peringkat", "ranking",
    "motivasi", "semangat", "keluhan program",
    # Plastic-education vocabulary so educational questions pass the gate.
    "pet", "hdpe", "pvc", "ldpe", "pp", "ps", "styrofoam",
    "kresek", "botol", "mikroplastik", "kode",
    "warga", "edukasi", "jelaskan", "jelasin",
    # Greetings — bare hello-style messages should reach the agent so it
    # can reply with a personalised status / opening line.
    "halo", "hai", "hi ", "mulai", "menu", "/start",
    # Help / "what can you do" — must reach the agent (capabilities reply),
    # never the off-topic gate.
    "bantuan", "bantu", "tolong", "help",
    # Emotional-state keywords — make sure quit / crisis signals always
    # reach the agent so the situation classifier can fire.
    "berhenti", "keluar", "nyerah", "menyerah", "mundur",
    "sanggup", "kuat", "lelah", "capek", "stres",
)

OFF_TOPIC_KEYWORDS = (
    "resep", "masak", "film", "drama", "musik", "lagu",
    "berita", "politik", "olahraga", "bola", "game",
    "cuaca", "ramalan", "zodiak", "teman", "pacar",
    "uang", "investasi", "saham", "crypto",
)

OFF_TOPIC_RESPONSE = (
    "Maaf, aku hanya bisa bantu soal program dan lingkungan hidup ya! 🌱 "
    "Ada yang ingin kamu tanyakan tentang misi atau plastik?"
)

TOPIC_CLASSIFY_PROMPT = (
    "Klasifikasikan pertanyaan volunteer ini. Balas HANYA dengan kata 'ya' "
    "kalau pertanyaan terkait program volunteer pengumpulan sampah plastik, "
    "lingkungan hidup, dampak karbon, atau motivasi mengikuti program. "
    "Balas 'tidak' untuk topik lain (hiburan, gosip, politik, finansial, dll)."
)

VALID_SITUATIONS = (
    "want_to_quit",
    "complaint",
    "motivation",
    "plastic_education",
    "general_qa",
)
DEFAULT_SITUATION = "general_qa"

# Deterministic shortcuts for want_to_quit — Haiku occasionally mis-classifies
# clear crisis language as ``complaint``, missing the fasilitator alert. These
# phrases force the want_to_quit path regardless of the LLM verdict.
QUIT_KEYWORD_TRIGGERS: tuple[str, ...] = (
    "mau berhenti",
    "ingin berhenti",
    "pengen berhenti",
    "mau keluar",
    "ingin keluar",
    "pengen keluar",
    "mundur",
    "menyerah",
    "nyerah",
    "ga sanggup",
    "tidak sanggup",
    "udah ga kuat",
    "udah tidak kuat",
)

ESCALATE_TAG = "[ESCALATE]"
HISTORY_LIMIT = 10


def is_allowed_topic(message: str) -> bool | None:
    """Cheap pre-check before any LLM call.

    Returns ``False`` for clearly off-topic, ``True`` for clearly on-topic,
    and ``None`` when the answer needs Claude to disambiguate.
    """
    lowered = message.lower()
    for keyword in OFF_TOPIC_KEYWORDS:
        if keyword in lowered:
            return False
    for topic in ALLOWED_TOPICS:
        if topic in lowered:
            return True
    return None


@register_intent(
    name="volunteer_support",
    description=(
        "masalah, keluhan, mau berhenti, butuh motivasi, pertanyaan umum, "
        "kebingungan, ATAU pertanyaan edukasi tentang plastik / daur ulang / "
        "lingkungan / mikroplastik / alternatif sekali pakai / cara edukasi "
        "warga"
    ),
    examples=(
        "capek banget pengen nyerah",
        "kenapa saya harus ikut program ini?",
        "saya mau berhenti jadi volunteer",
        "timbangan saya rusak, gimana dong?",
        "halo, bot ini bisa apa aja?",
        "minggu depan saya tidak bisa ikut, izin ya",
        "plastik PET itu apa?",
        "bedanya plastik kode 1 sama kode 2 gimana?",
        "kenapa plastik bahaya untuk lingkungan?",
        "mikroplastik itu berbahaya ga?",
        "gimana cara daur ulang yang bener?",
        "alternatif plastik sekali pakai apa aja?",
        "gimana cara jelasin ke warga yang ga mau dengerin?",
        "styrofoam bisa didaur ulang ga?",
        "kresek kode berapa?",
        "indonesia buang plastik berapa banyak?",
    ),
)
class VolunteerSupportAgent(BaseAgent):
    """Emotional support + plastic education for volunteers."""

    def __init__(self) -> None:
        super().__init__(
            name="volunteer_support",
            description="Emotional support + plastic education",
        )

    # ------------------------------------------------------------------ #
    # Main pipeline                                                       #
    # ------------------------------------------------------------------ #

    async def process(self, message: str, context: dict) -> str:
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        # Cross-volunteer query routed here when peer access is disabled.
        if context.get("_peer_query_denied"):
            return (
                "Hanya fasilitator yang bisa melihat data volunteer lain. "
                "Untuk lihat data kamu sendiri, tanya 'progress saya' atau "
                "'apa tugas saya'."
            )

        history = (
            await self.get_chat_history(telegram_id, limit=HISTORY_LIMIT)
            if telegram_id
            else []
        )

        # Topic gate — bail out before any LLM cost when clearly off-topic.
        # If the conversation already has on-topic history, skip the gate so
        # follow-up turns don't get bounced just because they reuse pronouns.
        topic_check = is_allowed_topic(message)
        if not history:
            if topic_check is False:
                return OFF_TOPIC_RESPONSE
            if topic_check is None and not await self.classify_topic_with_claude(
                message
            ):
                return OFF_TOPIC_RESPONSE

        volunteer_block = await self._build_volunteer_block(volunteer)
        system_prompt = build_system_prompt(volunteer_block)

        situation = await self._classify_situation(message)
        situation_directive = self._situation_directive(situation)
        if situation_directive:
            system_prompt = f"{system_prompt}\n\n{situation_directive}"

        messages = history + [{"role": "user", "content": message}]
        reply = await self.call_claude(
            system_prompt, messages, model=COMPLEX_MODEL, max_tokens=1200
        )

        if situation == "want_to_quit":
            name = (volunteer or {}).get("name") or "Volunteer"
            if ESCALATE_TAG not in reply:
                reply = f"{reply}\n\n{ESCALATE_TAG}"
            await alert_fasilitator(
                f"⚠️ {name} is considering quitting: {message}"
            )

        # Persist what the model actually produced (including the tag) so
        # the chat history records that an escalation happened.
        if telegram_id:
            await self.save_chat_history(
                telegram_id, "user", message, self.name
            )
            await self.save_chat_history(
                telegram_id, "assistant", reply, self.name
            )

        # Strip the tag before returning so the volunteer doesn't see it.
        return reply.replace(ESCALATE_TAG, "").strip()

    # ------------------------------------------------------------------ #
    # Situation classification                                            #
    # ------------------------------------------------------------------ #

    async def _classify_situation(self, message: str) -> str:
        lowered = (message or "").lower()
        if any(trigger in lowered for trigger in QUIT_KEYWORD_TRIGGERS):
            return "want_to_quit"
        try:
            verdict = await self.call_claude(
                CLASSIFY_PROMPT,
                [{"role": "user", "content": message}],
                model=DEFAULT_MODEL,
                max_tokens=10,
            )
        except Exception:
            return DEFAULT_SITUATION
        label = verdict.strip().lower().replace("`", "").replace('"', "")
        for candidate in VALID_SITUATIONS:
            if candidate in label:
                return candidate
        return DEFAULT_SITUATION

    @staticmethod
    def _situation_directive(situation: str) -> str | None:
        """Per-situation routing rules appended to the system prompt."""
        if situation == "want_to_quit":
            return (
                "=== SITUASI: VOLUNTEER INGIN BERHENTI ===\n"
                "- Empati dulu, dengarkan dulu — JANGAN langsung membujuk tetap.\n"
                "- Ajukan satu pertanyaan terbuka tentang apa yang membuat berat.\n"
                "- Jangan menggurui. Akui bahwa rasanya berat.\n"
                "- Tutup dengan sinyal bahwa fasilitator akan kontak personal.\n"
                "- Tambahkan tag [ESCALATE] di akhir respons."
            )
        if situation == "complaint":
            return (
                "=== SITUASI: KELUHAN ===\n"
                "- Empati dulu, baru solusi.\n"
                "- Untuk 'warga tidak mau': beri 3 tips persuasi konkret "
                "(boleh ambil dari skrip TIPS EDUKASI di knowledge base).\n"
                "- Untuk cuaca / kondisi lapangan: akui kesulitannya, lalu "
                "tawarkan workaround praktis (waktu lain, lokasi alternatif, "
                "buddy system)."
            )
        if situation == "motivation":
            return (
                "=== SITUASI: BUTUH MOTIVASI ===\n"
                "- Sebut data progress spesifik volunteer (kg / persentase / "
                "deadline) dari DATA VOLUNTEER di atas.\n"
                "- Hubungkan ke dampak nyata (botol diselamatkan, kg CO₂ "
                "dicegah) menggunakan angka.\n"
                "- Tetap singkat dan energik — jangan kuliah."
            )
        if situation == "plastic_education":
            return (
                "=== SITUASI: EDUKASI PLASTIK ===\n"
                "- Jawab fakta dengan minimal 1 angka konkret dari KNOWLEDGE "
                "BASE PLASTIK di atas.\n"
                "- Hubungkan ke konteks Indonesia bila relevan.\n"
                "- Bila volunteer minta 'cara menjelaskan ke warga', kasih "
                "skrip langsung pakai dari KNOWLEDGE BASE.\n"
                "- Tutup dengan langkah praktis yang volunteer bisa LAKUKAN "
                "dengan info ini."
            )
        return None

    # ------------------------------------------------------------------ #
    # Volunteer data block                                                #
    # ------------------------------------------------------------------ #

    async def _build_volunteer_block(self, volunteer: dict | None) -> str:
        if volunteer is None:
            return (
                "=== DATA VOLUNTEER ===\n"
                "Volunteer belum terdaftar dalam sistem. "
                "Sarankan ketik /start untuk daftar."
            )

        volunteer_id = volunteer.get("id")
        mission, assignment = await self._fetch_active_mission(volunteer_id)
        reported_kg, weeks_active = await self._fetch_progress(
            volunteer_id, str(mission.id) if mission else None
        )

        quota_kg = float(
            assignment.quota_kg.value
            if assignment
            else (volunteer.get("quota_kg") or 0)
        )
        pct = (reported_kg / quota_kg * 100) if quota_kg else 0
        area = (
            (assignment.assigned_area if assignment else None)
            or volunteer.get("area")
            or "-"
        )
        team_value = volunteer.get("team") or []
        team_str = ", ".join(team_value) if team_value else "belum ada data tim"

        deadline_date = mission.deadline if mission else None
        if deadline_date is not None:
            today = datetime.now(timezone.utc).date()
            days_left = (deadline_date - today).days
            deadline_str = deadline_date.isoformat()
            days_left_str = (
                f"{days_left} hari lagi" if days_left >= 0 else "sudah lewat"
            )
        else:
            deadline_str = "tidak diketahui"
            days_left_str = "-"

        status = self._derive_status(pct)

        return (
            "=== DATA VOLUNTEER ===\n"
            f"Nama: {volunteer.get('name') or '-'}\n"
            f"Area: {area}\n"
            f"Tim: {team_str}\n"
            f"Progress misi: {reported_kg:g}/{quota_kg:g} kg ({pct:.0f}%)\n"
            f"Minggu aktif: {weeks_active} minggu\n"
            f"Deadline: {deadline_str} ({days_left_str})\n"
            f"Status: {status}"
        )

    @staticmethod
    def _derive_status(pct: float) -> str:
        if pct >= 100:
            return "Sudah selesai 🎉"
        if pct >= 75:
            return "Hampir selesai"
        if pct >= 50:
            return "Setengah jalan"
        if pct > 0:
            return "Awal mula"
        return "Belum mulai"

    @staticmethod
    async def _fetch_active_mission(volunteer_id: str | None):
        """Active (Mission, MissionAssignment) entities for a volunteer, or (None, None)."""
        if not volunteer_id:
            return None, None
        from uuid import UUID

        from backend.infrastructure.composition_root import (
            build_mission_repository,
        )

        result = await build_mission_repository().get_active_for(
            UUID(str(volunteer_id))
        )
        return result if result is not None else (None, None)

    @staticmethod
    async def _fetch_progress(
        volunteer_id: str | None, mission_id: str | None
    ) -> tuple[float, int]:
        """Return ``(reported_kg, weeks_active)`` for a single volunteer."""
        if not volunteer_id:
            return 0.0, 0
        from uuid import UUID

        from backend.infrastructure.composition_root import (
            build_report_repository,
        )

        repo = build_report_repository()
        vid = UUID(str(volunteer_id))
        if mission_id:
            rows = await repo.list_for_volunteer_in_mission(
                vid, UUID(str(mission_id))
            )
        else:
            rows = await repo.list_for_volunteer(vid)
        total_kg = sum(r.kg_collected.value for r in rows)

        timestamps = [r.reported_at for r in rows if r.reported_at]
        if timestamps:
            earliest = min(timestamps)
            now = datetime.now(timezone.utc)
            weeks = max((now - earliest).days // 7, 1)
        else:
            weeks = 0
        return total_kg, weeks

    # ------------------------------------------------------------------ #
    # Topic gate Claude classifier (legacy, kept for back-compat)         #
    # ------------------------------------------------------------------ #

    async def classify_topic_with_claude(self, message: str) -> bool:
        """Tiny yes/no Claude call for ambiguous topic-gate cases.

        Uses up to 5 output tokens — far cheaper than the full reply path.
        On any classifier error, fail-open so a transient outage doesn't
        block legitimate volunteer questions.
        """
        try:
            verdict = await self.call_claude(
                TOPIC_CLASSIFY_PROMPT,
                [{"role": "user", "content": message}],
                model=DEFAULT_MODEL,
                max_tokens=5,
            )
        except Exception:
            return True
        return verdict.strip().lower().startswith("ya")
