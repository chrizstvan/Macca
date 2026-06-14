"""Mission briefing agent: answers questions about mission, area, quota, deadline, and SOP."""

import logging

from .base_agent import BaseAgent
from .intent_registry import register_intent
from .prompts.mission_briefing import BASE_PROMPT, SOP_SECTION
from backend.database.supabase_client import db

logger = logging.getLogger(__name__)

# Daily cap on free mission briefings per volunteer; further questions get a
# short canned reply that points to the program guide, saving Claude tokens.
MISSION_QUERY_DAILY_LIMIT = 2

QUOTA_REACHED_MSG = (
    "Kamu sudah 2x tanya tentang misi hari ini 😊 "
    "Untuk info lengkap silakan buka panduan program ya!"
)
LAST_FREE_NOTICE = (
    "\n\nIni adalah info misi terakhir yang bisa aku berikan hari ini. "
    "Kalau masih ada pertanyaan, cek panduan program ya! 📖"
)


@register_intent(
    name="mission_briefing",
    description=(
        "pertanyaan tentang tugas, area, kuota, deadline, SOP, cara pilah "
        "plastik, apa yang harus dilakukan"
    ),
    examples=(
        "apa tugas saya minggu ini?",
        "gimana cara bedain plastik pet sama hdpe?",
        "deadline misi kapan ya?",
        "area saya di mana?",
        "kuota saya berapa kg?",
        "apa yang harus saya lakukan hari ini?",
        "sop laporan gimana?",
    ),
)
class MissionBriefingAgent(BaseAgent):
    """Briefs volunteers on their mission, area, quota, deadline, progress, and SOP."""

    def __init__(self) -> None:
        super().__init__(
            name="mission_briefing",
            description="Answers questions about mission, task, area, quota, deadline, and SOP",
        )

    async def process(self, message: str, context: dict) -> str:
        """Answer a mission/SOP question with full volunteer + mission context."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        if context.get("persona") == "fasilitator":
            return await self._brief_fasilitator(message, context)

        if volunteer is None:
            volunteer = context.get("volunteer")
        if volunteer is None:
            return (
                "Kamu belum terdaftar sebagai volunteer. "
                "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
            )

        # Volunteer path → BriefMission use case.
        from uuid import UUID

        from backend.application.use_cases.brief_mission import (
            Brief,
            NotRegistered,
            QuotaCapped,
        )
        from backend.infrastructure.composition_root import build_brief_mission

        use_case = build_brief_mission()
        outcome = await use_case.execute(
            volunteer_id=UUID(str(volunteer["id"])),
            message=message,
            telegram_id=telegram_id,
        )

        if isinstance(outcome, NotRegistered):
            return (
                "Kamu belum terdaftar sebagai volunteer. "
                "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
            )
        if isinstance(outcome, QuotaCapped):
            return QUOTA_REACHED_MSG

        assert isinstance(outcome, Brief)
        response = outcome.text + (LAST_FREE_NOTICE if outcome.is_last_free_query else "")

        # 6. Return the response
        return response

    async def _brief_fasilitator(self, message: str, context: dict) -> str:
        """Fasilitator-persona briefing: every active mission + every assignment."""
        missions = self._fetch_active_missions_with_assignments()
        summary = self._format_fasilitator_briefing(missions)
        system_prompt = (
            BASE_PROMPT
            + "\n\nPERSONA: Fasilitator. Berikan info lengkap tentang semua misi "
            "aktif dan volunteer yang ter-assign. Boleh sertakan rekomendasi "
            "tindakan operasional."
            + f"\n\n{summary}\n\n{SOP_SECTION}"
        )
        telegram_id = context.get("telegram_id")
        history = await self.get_chat_history(telegram_id, limit=10)
        messages = history + [{"role": "user", "content": message}]
        response = await self.call_claude(system_prompt, messages, max_tokens=2000)
        await self.save_chat_history(telegram_id, "user", message, self.name)
        await self.save_chat_history(telegram_id, "assistant", response, self.name)
        return response

    @staticmethod
    def _fetch_active_missions_with_assignments() -> list[dict]:
        active = (
            db.table("missions").select("*").eq("status", "active").execute().data or []
        )
        out = []
        for mission in active:
            assignments = (
                db.table("volunteer_missions")
                .select(
                    "quota_kg, reported_kg, assigned_area, "
                    "volunteers(name, phone, telegram_id)"
                )
                .eq("mission_id", mission["id"])
                .execute()
                .data
                or []
            )
            out.append({"mission": mission, "assignments": assignments})
        return out

    @staticmethod
    def _format_fasilitator_briefing(missions: list[dict]) -> str:
        if not missions:
            return "Tidak ada misi aktif saat ini."
        lines: list[str] = []
        for entry in missions:
            mission = entry["mission"]
            lines.append(
                f"Misi: {mission.get('title')} — deadline {mission.get('deadline')}"
            )
            for assignment in entry["assignments"]:
                volunteer = assignment.get("volunteers") or {}
                quota = float(assignment.get("quota_kg") or 0)
                reported = float(assignment.get("reported_kg") or 0)
                lines.append(
                    f"  • {volunteer.get('name') or '?'} — "
                    f"{reported:g}/{quota:g} kg @ "
                    f"{assignment.get('assigned_area') or '-'}"
                )
        return "Data misi aktif:\n" + "\n".join(lines)

