"""Volunteer support agent that answers questions and provides guidance.

Adds a cheap keyword-based topic guardrail in front of the Claude call:
clearly off-topic messages get a canned reply with no LLM cost; clearly
on-topic ones go straight through; ambiguous ones are routed to a tiny
yes/no Claude call before deciding.
"""

from .base_agent import BaseAgent
from .prompts.volunteer_support import SYSTEM_PROMPT

ALLOWED_TOPICS = (
    "program", "misi", "tugas", "challenge",
    "plastik", "daur ulang", "lingkungan", "sampah",
    "karbon", "co2", "jejak karbon", "emisi",
    "submit", "laporan", "progress", "peringkat", "ranking",
    "motivasi", "semangat", "keluhan program",
)

OFF_TOPIC_KEYWORDS = (
    "resep", "masak", "film", "drama", "musik", "lagu",
    "berita", "politik", "olahraga", "bola", "game",
    "cuaca", "ramalan", "zodiak", "teman", "pacar",
    "uang", "investasi", "saham", "crypto",
)

OFF_TOPIC_RESPONSE = (
    "Maaf, aku hanya bisa bantu soal program dan lingkungan hidup ya! 🌱 "
    "Ada yang ingin kamu tanyakan tentang misi atau plastik?"
)

TOPIC_CLASSIFY_PROMPT = (
    "Klasifikasikan pertanyaan volunteer ini. Balas HANYA dengan kata 'ya' "
    "kalau pertanyaan terkait program volunteer pengumpulan sampah plastik, "
    "lingkungan hidup, dampak karbon, atau motivasi mengikuti program. "
    "Balas 'tidak' untuk topik lain (hiburan, gosip, politik, finansial, dll)."
)


def is_allowed_topic(message: str) -> bool | None:
    """Cheap pre-check before any LLM call.

    Returns ``False`` for clearly off-topic, ``True`` for clearly on-topic,
    and ``None`` when the answer needs Claude to disambiguate.
    """
    lowered = message.lower()
    for keyword in OFF_TOPIC_KEYWORDS:
        if keyword in lowered:
            return False
    for topic in ALLOWED_TOPICS:
        if topic in lowered:
            return True
    return None


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

        # Topic gate — short-circuit before the expensive Claude call.
        topic_check = is_allowed_topic(message)
        if topic_check is False:
            return OFF_TOPIC_RESPONSE
        if topic_check is None:
            if not await self.classify_topic_with_claude(message):
                return OFF_TOPIC_RESPONSE

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

    async def classify_topic_with_claude(self, message: str) -> bool:
        """Tiny yes/no Claude call for ambiguous messages.

        Uses up to 5 output tokens — far cheaper than the full reply path.
        On any classifier error, fail-open so a transient outage doesn't
        block legitimate volunteer questions.
        """
        try:
            verdict = await self.call_claude(
                TOPIC_CLASSIFY_PROMPT,
                [{"role": "user", "content": message}],
                max_tokens=5,
            )
        except Exception:
            return True
        return verdict.strip().lower().startswith("ya")
