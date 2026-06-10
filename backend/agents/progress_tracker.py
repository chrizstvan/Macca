"""Progress tracker agent that handles collection reports and status checks."""

from .base_agent import BaseAgent
from backend.database.supabase_client import db

SYSTEM_PROMPT = (
    "You are the Progress Tracker for Macca, a volunteer coordination platform for waste "
    "collection missions. Volunteers send collection reports like 'laporan 18 kg menteng' "
    "or ask about their progress toward their quota. "
    "When the user is reporting a collection, confirm the amount and location back to them. "
    "When they ask for status, summarise their progress using the data provided. "
    "Be concise, supportive, and data-driven. Format for Telegram."
)


class ProgressTrackerAgent(BaseAgent):
    """Processes collection reports (laporan) and answers progress/status queries."""

    def __init__(self) -> None:
        super().__init__(
            name="progress_tracker",
            description="Handles collection reports and progress status checks",
        )

    async def process(self, message: str, context: dict) -> str:
        """Respond to a report or status query with the volunteer's progress data."""
        telegram_id = context.get("telegram_id")

        extra = ""
        if telegram_id:
            volunteer = await self.get_volunteer(telegram_id)
            if volunteer:
                reports = (
                    db.table("reports")
                    .select("kg_collected, location, reported_at, verified")
                    .eq("volunteer_id", volunteer["id"])
                    .order("reported_at", desc=True)
                    .limit(10)
                    .execute()
                    .data
                    or []
                )
                total = sum(float(r["kg_collected"]) for r in reports)
                extra = (
                    f"\n\nVolunteer: name={volunteer.get('name')}, area={volunteer.get('area')}, "
                    f"quota={volunteer.get('quota_kg')} kg. "
                    f"Total reported so far: {total} kg. Recent reports: {reports}"
                )
            else:
                extra = "\n\nThis user is not yet registered as a volunteer."

        history = await self.get_chat_history(telegram_id) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]

        return await self.call_claude(SYSTEM_PROMPT + extra, messages)
