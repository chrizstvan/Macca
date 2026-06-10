"""Mission briefing agent that explains mission details and assignments."""

from .base_agent import BaseAgent
from backend.database.supabase_client import db

SYSTEM_PROMPT = (
    "You are the Mission Briefing officer for Macca, a volunteer coordination platform "
    "for waste collection missions. Answer questions about mission objectives, deadlines, "
    "assigned areas, and quotas using the mission data provided. "
    "Be clear, motivating, and actionable. Format for Telegram (bold and emoji sparingly)."
)


class MissionBriefingAgent(BaseAgent):
    """Briefs volunteers on active missions, deadlines, areas, and quotas."""

    def __init__(self) -> None:
        super().__init__(
            name="mission_briefing",
            description="Explains mission details, deadlines, and assignments",
        )

    async def process(self, message: str, context: dict) -> str:
        """Answer a mission question using active mission data from the database."""
        telegram_id = context.get("telegram_id")

        missions = (
            db.table("missions").select("*").eq("status", "active").execute().data or []
        )
        extra = f"\n\nActive missions: {missions}" if missions else "\n\nNo active missions."

        if telegram_id:
            volunteer = await self.get_volunteer(telegram_id)
            if volunteer:
                extra += (
                    f"\nVolunteer: name={volunteer.get('name')}, "
                    f"area={volunteer.get('area')}, quota={volunteer.get('quota_kg')} kg."
                )

        history = await self.get_chat_history(telegram_id) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]

        return await self.call_claude(SYSTEM_PROMPT + extra, messages)
