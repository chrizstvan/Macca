"""Content creator agent that drafts social posts, reports, and campaign material."""

from .base_agent import BaseAgent, COMPLEX_MODEL
from .intent_registry import register_intent
from .prompts.content_creator import SYSTEM_PROMPT


@register_intent(
    name="content_creator",
    description=(
        "minta dibuatkan konten media sosial, caption, post, teks pengumuman"
    ),
    examples=(
        "buatkan caption instagram hari ini",
        "tolong bikin post story wa tentang misi minggu ini",
        "bikin teks pengumuman buat grup dong",
    ),
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
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        history = await self.get_chat_history(telegram_id) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]

        reply = await self.call_claude(
            SYSTEM_PROMPT, messages, model=COMPLEX_MODEL, max_tokens=2000
        )
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply
