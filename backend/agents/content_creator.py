"""Content creator agent that drafts social posts, reports, and campaign material."""

from .base_agent import BaseAgent, COMPLEX_MODEL

SYSTEM_PROMPT = (
    "You are the Content Creator for Macca, a volunteer coordination platform for waste "
    "collection missions. Write compelling, authentic content highlighting volunteer "
    "impact and mission outcomes. "
    "Social posts should be punchy and shareable; impact reports data-focused and "
    "professional; volunteer stories personal and inspiring. "
    "Avoid jargon. Include a clear call-to-action where appropriate."
)


class ContentCreatorAgent(BaseAgent):
    """Drafts campaign and communication content on request."""

    def __init__(self) -> None:
        super().__init__(
            name="content_creator",
            description="Drafts social posts, stories, and campaign content",
        )

    async def process(self, message: str, context: dict) -> str:
        """Generate content from the brief, using the stronger model for quality."""
        telegram_id = context.get("telegram_id")

        history = await self.get_chat_history(telegram_id) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]

        return await self.call_claude(
            SYSTEM_PROMPT, messages, model=COMPLEX_MODEL, max_tokens=2000
        )
