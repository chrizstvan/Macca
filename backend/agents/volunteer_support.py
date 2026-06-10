"""Volunteer support agent that answers questions and provides guidance."""

from .base_agent import BaseAgent

SYSTEM_PROMPT = (
    "You are a friendly volunteer support assistant for Macca, a volunteer coordination "
    "platform for waste collection missions. Help volunteers with questions about their "
    "missions, quotas, areas, reporting, and general guidance. "
    "Be warm, clear, and concise. If a question requires human intervention, say so "
    "explicitly and indicate that a fasilitator will follow up. Format for Telegram."
)


class VolunteerSupportAgent(BaseAgent):
    """General-purpose support agent: FAQs, onboarding, and logistics questions."""

    def __init__(self) -> None:
        super().__init__(
            name="volunteer_support",
            description="Answers volunteer FAQs and general questions",
        )

    async def process(self, message: str, context: dict) -> str:
        """Reply to a support query using recent chat history and the volunteer profile."""
        telegram_id = context.get("telegram_id")

        extra = ""
        if telegram_id:
            volunteer = await self.get_volunteer(telegram_id)
            if volunteer:
                extra = (
                    f"\n\nVolunteer profile: name={volunteer.get('name')}, "
                    f"area={volunteer.get('area')}, quota={volunteer.get('quota_kg')} kg."
                )
            else:
                extra = "\n\nThis user is not yet registered as a volunteer."

        history = await self.get_chat_history(telegram_id) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]

        return await self.call_claude(SYSTEM_PROMPT + extra, messages)
