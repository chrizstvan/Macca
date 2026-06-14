"""WhatsApp-inbound onboarding flow.

Runs before the router dispatches. Three scenarios:

A. **First contact (pre-registered).** Phone exists in ``volunteers`` but
   ``whatsapp_connected`` is False. Mark connected, alert the fasilitator,
   queue a welcome message ahead of normal routing.
B. **Unknown phone.** No volunteer row for the phone. Save to
   ``unknown_contacts``, alert the fasilitator, reply with a redirect —
   do NOT route to any agent.
C. **Returning volunteer.** Phone exists, already connected. Touch
   ``last_contact_at``. If the message is a greeting, return a short
   status summary instead of routing; otherwise proceed normally.

Fasilitator phone bypasses the whole flow — see
``backend.agents.router_agent`` for fasilitator detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from backend.application.ports.clock import Clock
from backend.application.ports.mission_repository import MissionRepository
from backend.application.ports.notifier import Notifier
from backend.application.ports.report_repository import ReportRepository
from backend.application.ports.unknown_contact_repository import (
    UnknownContactRepository,
)
from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.domain.value_objects.phone import Phone
from backend.utils.phone_utils import normalize_phone

GREETING_TOKENS: tuple[str, ...] = (
    "halo", "hi", "hai", "mulai", "/start", "/mulai", "menu", "hello",
)

WELCOME_TEMPLATE = (
    "Halo {name}! 👋 Selamat datang di WhatsApp Macca — Generasi Bebas Plastik.\n\n"
    "Nomor kamu sudah terhubung dengan akun volunteer. Kamu bisa mulai "
    "kirim laporan, tanya misi, atau minta dukungan kapan saja di chat ini.\n\n"
    "Ketik *halo* atau */mulai* untuk lihat ringkasan status kamu."
)

UNKNOWN_REDIRECT = (
    "Hai! Nomor kamu belum terdaftar sebagai volunteer. 🙏\n"
    "Hubungi fasilitator program untuk informasi pendaftaran ya."
)


# --------------------------------------------------------------------------- #
# Outcome ADT                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReplyAndContinue:
    """Send these messages first, then dispatch the original to the router."""

    pre_messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReplyAndStop:
    """Reply with this text; skip router dispatch entirely."""

    text: str


@dataclass(frozen=True)
class ContinueOnly:
    """Nothing to send; router takes over."""


InboundContactOutcome = ReplyAndContinue | ReplyAndStop | ContinueOnly


# --------------------------------------------------------------------------- #
# Use case                                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class HandleInboundContact:
    volunteers: VolunteerRepository
    missions: MissionRepository
    reports: ReportRepository
    unknown_contacts: UnknownContactRepository
    notifier: Notifier
    clock: Clock

    async def execute(
        self, *, sender_phone: str, message: str
    ) -> InboundContactOutcome:
        canonical = normalize_phone(sender_phone)
        if not canonical:
            return ContinueOnly()

        phone = Phone.try_parse(canonical)
        volunteer = await self.volunteers.get_by_phone(phone) if phone else None

        if volunteer is None:
            # Scenario B — unknown phone.
            preview = (message or "")[:50]
            await self.unknown_contacts.record(
                phone=canonical, message_preview=message or ""
            )
            await self.notifier.alert_fasilitator(
                f"👤 Pesan dari nomor tidak dikenal: {canonical}\n"
                f"Pesan: '{preview}...'\n"
                "Tambahkan ke dashboard jika ini volunteer."
            )
            return ReplyAndStop(text=UNKNOWN_REDIRECT)

        now = self.clock.now()
        is_first = volunteer.mark_contacted(now)
        await self.volunteers.save(volunteer)

        if is_first:
            # Scenario A — first contact.
            await self.notifier.alert_fasilitator(
                f"✅ {volunteer.name} just connected via WhatsApp "
                f"({canonical})."
            )
            return ReplyAndContinue(
                pre_messages=[WELCOME_TEMPLATE.format(name=volunteer.name)]
            )

        # Scenario C — returning volunteer.
        if self._is_greeting(message):
            text = await self._build_status_summary(
                volunteer_id=volunteer.id,
                name=volunteer.name,
                today=self.clock.today(),
            )
            return ReplyAndStop(text=text)

        return ContinueOnly()

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_greeting(message: str) -> bool:
        if not message:
            return False
        lowered = message.strip().lower()
        return lowered in GREETING_TOKENS or any(
            lowered.startswith(t + " ") for t in GREETING_TOKENS
        )

    async def _build_status_summary(
        self, *, volunteer_id: UUID, name: str, today: date
    ) -> str:
        active = await self.missions.get_active_for(volunteer_id)
        if active is None:
            return (
                f"Halo lagi, {name}! 👋\n"
                "Belum ada misi aktif untuk kamu saat ini. "
                "Fasilitator akan menginformasikan misi berikutnya ya 🙏\n"
                "Ada yang bisa saya bantu?"
            )

        mission, assignment = active
        quota = assignment.quota_kg.value
        reported_kg = await self.reports.total_kg_for(volunteer_id, mission.id)
        pct = (reported_kg / quota * 100) if quota else 0

        deadline = mission.deadline
        if deadline is not None:
            days_left = (deadline - today).days
            deadline_line = (
                f"⏰ Deadline: {deadline.isoformat()} ({days_left} hari lagi)\n"
            )
        else:
            deadline_line = "⏰ Deadline: belum ditentukan\n"

        return (
            f"Halo lagi, {name}! 👋\n"
            f"📦 Progress: {reported_kg:g}/{quota:g} kg ({pct:.0f}%)\n"
            f"{deadline_line}"
            "Ada yang bisa saya bantu?"
        )
