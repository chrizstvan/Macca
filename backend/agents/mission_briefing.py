"""Mission briefing agent: answers questions about mission, area, quota, deadline, and SOP."""

import logging
from datetime import date, datetime, timezone

from .base_agent import BaseAgent
from .prompts.mission_briefing import BASE_PROMPT, SOP_SECTION
from backend.database.supabase_client import db
from backend.utils.date_utils import parse_iso_date as _shared_parse_iso_date
from backend.utils.query_utils import get_active_mission as _shared_get_active_mission

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

        # 2. Volunteer profile (already loaded by the router/handler)
        if volunteer is None:
            volunteer = context.get("volunteer")
        if volunteer is None:
            return (
                "Kamu belum terdaftar sebagai volunteer. "
                "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
            )

        # 1a. Daily quota: skip Claude entirely if the volunteer is over budget.
        count, over_limit = self._consume_quota(volunteer)
        if over_limit:
            return QUOTA_REACHED_MSG

        # 1. Active mission from volunteer_missions + missions
        mission, assignment = self._get_active_mission(volunteer["id"])
        progress_kg = self._get_progress_kg(
            volunteer["id"], mission["id"] if mission else None
        )

        # 3. Rich system prompt with profile, mission, progress, and SOP
        system_prompt = self._build_system_prompt(volunteer, mission, assignment, progress_kg)

        # 4. Claude Haiku with last 10 chat messages + current message
        history = await self.get_chat_history(telegram_id, limit=10) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]
        response = await self.call_claude(system_prompt, messages)

        # Append a "last free query" notice when this call uses up the budget.
        if count == MISSION_QUERY_DAILY_LIMIT - 1:
            response += LAST_FREE_NOTICE

        # 5. Persist both sides of the exchange
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", response, self.name)

        # 6. Return the response
        return response

    @staticmethod
    def _get_active_mission(
        volunteer_id: str,
    ) -> tuple[dict | None, dict | None]:
        """Return (mission, assignment) for the volunteer's active mission."""
        return _shared_get_active_mission(volunteer_id, with_assignment=True)

    def _get_progress_kg(self, volunteer_id: str, mission_id: str | None) -> float:
        """Sum of kg reported by this volunteer (scoped to the mission when known)."""
        query = db.table("reports").select("kg_collected").eq("volunteer_id", volunteer_id)
        if mission_id:
            query = query.eq("mission_id", mission_id)
        result = query.execute()
        return sum(float(r["kg_collected"]) for r in result.data or [])

    def _build_system_prompt(
        self,
        volunteer: dict,
        mission: dict | None,
        assignment: dict | None,
        progress_kg: float,
    ) -> str:
        team = volunteer.get("team") or []
        quota = (assignment or {}).get("quota_kg") or volunteer.get("quota_kg") or 0
        area = (assignment or {}).get("assigned_area") or volunteer.get("area") or "-"

        volunteer_section = (
            f"Data volunteer:\n"
            f"- Nama: {volunteer.get('name')}\n"
            f"- Area tugas: {area}\n"
            f"- Tim: {', '.join(team) if team else 'belum ada data tim'}\n"
            f"- Kuota: {float(quota):g} kg"
        )

        if mission:
            remaining = self._remaining_days(mission.get("deadline"))
            remaining_text = (
                f"{remaining} hari lagi" if remaining is not None and remaining >= 0
                else "sudah lewat" if remaining is not None
                else "tidak diketahui"
            )
            mission_section = (
                f"Misi aktif:\n"
                f"- Judul: {mission.get('title')}\n"
                f"- Deskripsi: {mission.get('description') or '-'}\n"
                f"- Deadline: {mission.get('deadline')} ({remaining_text})\n"
                f"- Progress {volunteer.get('name')}: {progress_kg:g} kg "
                f"dari kuota {float(quota):g} kg"
            )
        else:
            mission_section = (
                "Misi aktif: belum ada misi yang diassign ke volunteer ini. "
                "Fasilitator akan menginformasikan misi berikutnya."
            )

        return f"{BASE_PROMPT}\n\n{volunteer_section}\n\n{mission_section}\n\n{SOP_SECTION}"

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

    def _consume_quota(self, volunteer: dict) -> tuple[int, bool]:
        """Update the volunteer's daily mission-query budget and report the state.

        Returns ``(count_before_this_call, over_limit)``.

        ``count_before_this_call`` is the count this request is allowed to use
        (so the caller can decide whether to append the "last free" notice).
        ``over_limit`` is True when the volunteer has already hit the cap
        today — caller should return the canned reply and skip the LLM call.

        If the schema columns are missing (dev environments without the
        migration), no enforcement happens and ``(0, False)`` is returned.
        """
        try:
            raw_reset = volunteer.get("mission_query_reset_at")
            raw_count = int(volunteer.get("mission_query_count") or 0)
        except (TypeError, ValueError):
            return 0, False

        reset_date = self._parse_date(raw_reset)
        today = date.today()

        # Daily reset — new day means a fresh budget.
        if reset_date is None or reset_date < today:
            raw_count = 0
            self._write_count(volunteer["id"], 0, today)

        if raw_count >= MISSION_QUERY_DAILY_LIMIT:
            return raw_count, True

        # Reserve this slot before the LLM call so concurrent retries can't
        # both pass the gate.
        self._write_count(volunteer["id"], raw_count + 1, today)
        return raw_count, False

    _parse_date = staticmethod(_shared_parse_iso_date)

    @staticmethod
    def _write_count(volunteer_id: str, new_count: int, reset_at: date) -> None:
        try:
            (
                db.table("volunteers")
                .update(
                    {
                        "mission_query_count": new_count,
                        "mission_query_reset_at": reset_at.isoformat(),
                    }
                )
                .eq("id", volunteer_id)
                .execute()
            )
        except Exception as exc:
            # Schema migration may not have run yet; degrade to no-limit mode.
            logger.warning("mission_query_count update failed: %s", exc)

    @staticmethod
    def _remaining_days(deadline: str | None) -> int | None:
        if not deadline:
            return None
        try:
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            return (deadline_dt - datetime.now(timezone.utc)).days
        except ValueError:
            logger.warning("Unparseable mission deadline: %r", deadline)
            return None
