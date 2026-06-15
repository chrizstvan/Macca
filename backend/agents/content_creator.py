"""Social-media content creator agent.

Pulls today's program data from Supabase, picks a platform + tone from the
brief, then asks Sonnet for a ready-to-post caption that respects the
platform's character and hashtag limits. Also exposes
``daily_content_summary()`` for the 20:00 scheduled job, which DMs the
fasilitator a draft Instagram caption every evening.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.agents.services.notifications import alert_fasilitator
from backend.database.supabase_client import db

from .base_agent import BaseAgent, COMPLEX_MODEL
from .intent_registry import register_intent
from .prompts.content_creator import (
    DEFAULT_PLATFORM,
    DEFAULT_TONE,
    PLATFORM_CONSTRAINTS,
    REQUIRED_HASHTAGS,
    SYSTEM_PROMPT,
    TONE_GUIDANCE,
)

logger = logging.getLogger(__name__)

PLATFORM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("instagram", ("instagram", "ig ", " ig", "/ig", "insta")),
    ("twitter", ("twitter", " x ", "x.com", "/x", "tweet")),
    ("whatsapp", ("whatsapp", " wa ", "/wa", "story wa", "broadcast wa")),
    ("tiktok", ("tiktok", " tt ", "/tt", "tik tok")),
)

TONE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("edukatif", ("edukatif", "edukasi", "informasi")),
    ("formal", ("formal", "resmi", "stakeholder", "donor", "sponsor")),
    ("santai", ("santai", "casual", "kasual")),
    ("semangat", ("semangat", "energik", "motivasi", "ajak")),
)

MILESTONE_THRESHOLDS_KG: tuple[int, ...] = (100, 250, 500, 1000, 2500, 5000)
HASHTAG_TARGET_BY_PLATFORM_DEFAULT = 12


# --------------------------------------------------------------------------- #
# Agent                                                                        #
# --------------------------------------------------------------------------- #


@register_intent(
    name="content_creator",
    description=(
        "minta dibuatkan konten media sosial, caption, post, teks pengumuman"
    ),
    examples=(
        "buatkan caption instagram hari ini",
        "tolong bikin post story wa tentang misi minggu ini",
        "bikin teks pengumuman buat grup dong",
        "tweet pendek soal progres program",
        "caption tiktok untuk reels hari ini",
    ),
)
class ContentCreatorAgent(BaseAgent):
    """Drafts platform-aware social posts grounded in today's program data."""

    def __init__(self) -> None:
        super().__init__(
            name="content_creator",
            description="Drafts social posts, stories, and campaign content",
        )

    # ------------------------------------------------------------------ #
    # Main entry                                                          #
    # ------------------------------------------------------------------ #

    async def process(self, message: str, context: dict) -> str:
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        platform = self._detect_platform(message)
        tone = self._detect_tone(message)

        daily = self._aggregate_today()
        system_prompt = self._build_system_prompt(
            platform=platform, tone=tone, daily=daily
        )

        history = (
            await self.get_chat_history(telegram_id) if telegram_id else []
        )
        messages = history + [{"role": "user", "content": message}]

        reply = await self.call_claude(
            system_prompt,
            messages,
            model=COMPLEX_MODEL,
            max_tokens=2000,
        )
        reply = self._ensure_required_hashtags(reply)

        if telegram_id:
            await self.save_chat_history(
                telegram_id, "user", message, self.name
            )
            await self.save_chat_history(
                telegram_id, "assistant", reply, self.name
            )
        return reply

    # ------------------------------------------------------------------ #
    # Scheduled daily summary                                             #
    # ------------------------------------------------------------------ #

    async def daily_content_summary(self) -> str:
        """Generate today's Instagram draft and DM it to the fasilitator.

        Called by the scheduler at 20:00 (cron set in ``backend/main.py``).
        Returns the generated content so callers + tests can inspect it.
        """
        daily = self._aggregate_today()
        system_prompt = self._build_system_prompt(
            platform="instagram", tone="semangat", daily=daily
        )
        content = await self.call_claude(
            system_prompt,
            [
                {
                    "role": "user",
                    "content": (
                        "Buat caption Instagram untuk dampak hari ini, tone "
                        "semangat, siap di-post."
                    ),
                }
            ],
            model=COMPLEX_MODEL,
            max_tokens=2000,
        )
        content = self._ensure_required_hashtags(content)
        await alert_fasilitator(
            "📱 Konten harian siap! Tinggal approve dan post:\n\n" + content
        )
        return content

    # ------------------------------------------------------------------ #
    # Detection helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_platform(message: str) -> str:
        lowered = f" {(message or '').lower()} "
        for canonical, triggers in PLATFORM_KEYWORDS:
            if any(t in lowered for t in triggers):
                return canonical
        return DEFAULT_PLATFORM

    @staticmethod
    def _detect_tone(message: str) -> str:
        lowered = (message or "").lower()
        for canonical, triggers in TONE_KEYWORDS:
            if any(t in lowered for t in triggers):
                return canonical
        return DEFAULT_TONE

    # ------------------------------------------------------------------ #
    # Prompt assembly                                                     #
    # ------------------------------------------------------------------ #

    def _build_system_prompt(
        self,
        *,
        platform: str,
        tone: str,
        daily: dict[str, Any],
    ) -> str:
        constraints = PLATFORM_CONSTRAINTS.get(
            platform, PLATFORM_CONSTRAINTS[DEFAULT_PLATFORM]
        )
        max_chars = constraints["max_chars"]
        hashtag_range = constraints["hashtag_range"]
        guidance = constraints["guidance"]
        tone_block = TONE_GUIDANCE.get(tone, TONE_GUIDANCE[DEFAULT_TONE])

        locations = ", ".join(daily["locations"][:6]) or "-"
        top_block = (
            f"{daily['top_volunteer_name']} ({daily['top_volunteer_kg']:g} kg)"
            if daily["top_volunteer_name"]
            else "-"
        )
        milestone_block = (
            ", ".join(f"{m:g} kg" for m in daily["milestones"])
            if daily["milestones"]
            else "tidak ada milestone baru"
        )

        data_block = (
            "=== DATA DAMPAK HARI INI ===\n"
            f"Total terkumpul: {daily['total_kg_today']:g} kg\n"
            f"Volunteer aktif lapor: {daily['active_volunteers']} orang\n"
            f"Lokasi tercakup: {locations}\n"
            f"Top volunteer: {top_block}\n"
            f"Botol setara (≈71/kg): {daily['bottles_today']:,}\n"
            f"CO₂ dicegah (≈3 kg/kg): {daily['co2_today']:g} kg\n"
            f"Milestone baru: {milestone_block}\n"
            f"Program total hingga sekarang: {daily['program_total_kg']:g} kg"
        )

        constraint_block = (
            "=== PLATFORM CONSTRAINTS ===\n"
            f"Platform: {platform}\n"
            f"Karakter maksimum: {max_chars}\n"
            f"Jumlah hashtag target: {hashtag_range[0]}-{hashtag_range[1]}\n"
            f"Petunjuk: {guidance}"
        )

        required = ", ".join(REQUIRED_HASHTAGS)
        footer = (
            "=== WAJIB ===\n"
            f"Sertakan TIGA hashtag wajib di akhir: {required}\n"
            "Jangan menulis instruksi atau penjelasan — keluarkan caption "
            "siap-copy saja."
        )

        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"{data_block}\n\n"
            f"{constraint_block}\n\n"
            f"{tone_block}\n\n"
            f"{footer}"
        )

    # ------------------------------------------------------------------ #
    # Post-processing                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _ensure_required_hashtags(text: str) -> str:
        missing = [
            tag for tag in REQUIRED_HASHTAGS if tag.lower() not in text.lower()
        ]
        if not missing:
            return text
        sep = "" if text.endswith(("\n", " ")) else " "
        return f"{text}{sep}{' '.join(missing)}"

    # ------------------------------------------------------------------ #
    # Today aggregation                                                   #
    # ------------------------------------------------------------------ #

    def _aggregate_today(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        today_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        rows = (
            db.table("reports")
            .select("volunteer_id, kg_collected, location, reported_at")
            .gte("reported_at", today_start)
            .execute()
            .data
            or []
        )

        total_kg_today = sum(float(r.get("kg_collected") or 0) for r in rows)
        active_volunteer_ids = {r.get("volunteer_id") for r in rows}
        locations = sorted(
            {(r.get("location") or "").strip() for r in rows if r.get("location")}
        )

        kg_by_volunteer: dict[str, float] = defaultdict(float)
        for row in rows:
            kg_by_volunteer[row["volunteer_id"]] += float(
                row.get("kg_collected") or 0
            )
        top_volunteer_id: str | None = None
        top_volunteer_kg = 0.0
        if kg_by_volunteer:
            top_volunteer_id, top_volunteer_kg = max(
                kg_by_volunteer.items(), key=lambda kv: kv[1]
            )

        top_volunteer_name = ""
        if top_volunteer_id:
            row = (
                db.table("volunteers")
                .select("name")
                .eq("id", top_volunteer_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            if row:
                top_volunteer_name = row[0].get("name") or ""

        # Program totals: before-today + today = current. Detect milestone crossings.
        program_before = self._sum_reports_before(today_start)
        program_total_now = program_before + total_kg_today
        milestones = [
            t
            for t in MILESTONE_THRESHOLDS_KG
            if program_before < t <= program_total_now
        ]

        bottles_today = int(round(total_kg_today * 71))
        co2_today = round(total_kg_today * 3, 1)

        return {
            "total_kg_today": round(total_kg_today, 2),
            "active_volunteers": len(active_volunteer_ids),
            "locations": locations,
            "top_volunteer_name": top_volunteer_name,
            "top_volunteer_kg": round(top_volunteer_kg, 2),
            "milestones": milestones,
            "program_total_kg": round(program_total_now, 2),
            "bottles_today": bottles_today,
            "co2_today": co2_today,
        }

    @staticmethod
    def _sum_reports_before(timestamp_iso: str) -> float:
        rows = (
            db.table("reports")
            .select("kg_collected")
            .lt("reported_at", timestamp_iso)
            .execute()
            .data
            or []
        )
        return sum(float(r.get("kg_collected") or 0) for r in rows)
