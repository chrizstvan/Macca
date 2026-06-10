"""Fasilitator hub agent providing operational tools for mission facilitators."""

from .base_agent import BaseAgent
from backend.config import settings
from backend.database.supabase_client import db

SYSTEM_PROMPT = (
    "You are the Fasilitator Hub assistant for Macca, a volunteer coordination platform "
    "for waste collection missions. You assist the fasilitator who coordinates volunteers "
    "on the ground. Provide concise operational summaries, highlight flagged reports that "
    "need verification, surface volunteers behind on quota, and help draft broadcasts. "
    "Tone: efficient, clear, action-oriented. Format for Telegram."
)


class FasilitatorHubAgent(BaseAgent):
    """Operational summaries, flagged-report digests, and broadcast drafting for fasilitators."""

    def __init__(self) -> None:
        super().__init__(
            name="fasilitator_hub",
            description="Operational tools and summaries for fasilitators",
        )

    async def process(self, message: str, context: dict) -> str:
        """Handle a fasilitator request; non-fasilitators are redirected politely."""
        telegram_id = context.get("telegram_id")

        if telegram_id != settings.fasilitator_telegram_id:
            return (
                "This command is only available to the fasilitator. "
                "If you need help, just ask me a question directly!"
            )

        volunteers = db.table("volunteers").select("name, area, quota_kg, is_active").execute().data or []
        flagged = (
            db.table("reports")
            .select("kg_collected, location, flag_reason, reported_at")
            .eq("is_flagged", True)
            .eq("verified", False)
            .execute()
            .data
            or []
        )
        extra = (
            f"\n\nVolunteers ({len(volunteers)}): {volunteers}"
            f"\nUnverified flagged reports ({len(flagged)}): {flagged}"
        )

        history = await self.get_chat_history(telegram_id)
        messages = history + [{"role": "user", "content": message}]

        return await self.call_claude(SYSTEM_PROMPT + extra, messages, max_tokens=2000)
