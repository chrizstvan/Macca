"""Volunteer support agent that answers questions and provides guidance."""

from .base_agent import BaseAgent
from .prompts.volunteer_support import SYSTEM_PROMPT


class VolunteerSupportAgent(BaseAgent):
    """General-purpose support agent: FAQs, onboarding, and logistics questions."""

    def __init__(self) -> None:
        super().__init__(
            name="volunteer_support",
            description="Answers volunteer FAQs and general questions",
        )

    async def process(self, message: str, context: dict) -> str:
        """Reply to a support query using recent chat history and the volunteer profile."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        if volunteer:
            extra = (
                f"\n\nVolunteer profile: name={volunteer.get('name')}, "
                f"area={volunteer.get('area')}, quota={volunteer.get('quota_kg')} kg."
            )
        else:
            extra = "\n\nThis user is not yet registered as a volunteer."

        history = await self.get_chat_history(telegram_id) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]

        reply = await self.call_claude(SYSTEM_PROMPT + extra, messages)
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply
