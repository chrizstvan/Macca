"""Education-content draft generator.

Generates a WhatsApp-group education post on a rotating plastic/climate topic.
DRAFT ONLY — the output goes to the fasilitator to copy-paste into the group;
it is never broadcast to volunteers (unlike quizzes, which feed ranking).

Parallels ``quiz_generator`` / ``reminder_generator``: a thin presentation
helper. Persistence (``content_drafts``) and the every-3-days cadence live in
the scheduler job; edits go through the fasilitator-hub education mixin.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .base_agent import BaseAgent, COMPLEX_MODEL

logger = logging.getLogger(__name__)

# Rotating education topics (group audience, general — not personalised).
TOPICS: tuple[str, ...] = (
    "fakta mengejutkan tentang mikroplastik",
    "hubungan plastik dan jejak karbon",
    "dampak plastik ke perubahan iklim",
    "cara memilah plastik yang benar",
    "alternatif pengganti plastik sekali pakai",
    "kondisi sampah plastik di laut Indonesia",
    "plastik dan kesehatan manusia",
)


class EducationContentGenerator(BaseAgent):
    """Topic-rotating plastic-education content for the volunteer group."""

    def __init__(self) -> None:
        super().__init__(
            name="education_generator",
            description="Generates plastic-education group content drafts.",
        )

    async def process(self, message: str, context: dict) -> str:
        """BaseAgent entry — generate on the current rotation topic."""
        topic = self.topic_for(self.rotation_index())
        return await self.generate(topic)

    # ------------------------------------------------------------------ #
    # Topic rotation                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def rotation_index() -> int:
        """Deterministic rotation pointer derived from the date."""
        return datetime.now(timezone.utc).timetuple().tm_yday // 3

    @classmethod
    def topic_for(cls, index: int) -> str:
        return TOPICS[index % len(TOPICS)]

    # ------------------------------------------------------------------ #
    # Generation                                                         #
    # ------------------------------------------------------------------ #

    async def generate(self, topic: str, guidance: str | None = None) -> str:
        """Generate group education content on ``topic`` (optionally revised)."""
        system_prompt = (
            "Buat konten edukasi WhatsApp untuk grup volunteer lingkungan "
            f"tentang: {topic}.\n"
            "Format: menarik, mudah dipahami, 5-8 baris, ada 1-2 fakta konkret "
            "dengan angka, diakhiri ajakan/refleksi singkat. Emoji secukupnya. "
            "Ini untuk grup, tulis untuk audiens umum (bukan 1 orang)."
        )
        if guidance:
            system_prompt += f"\n\nRevisi sesuai instruksi: {guidance}"

        return await self.call_claude(
            system_prompt,
            [{"role": "user", "content": "Buat konten edukasi."}],
            model=COMPLEX_MODEL,
        )

    # ------------------------------------------------------------------ #
    # Formatting                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_draft_message(topic: str, content: str) -> str:
        """Fasilitator-facing draft (copy-paste ready)."""
        return (
            "📚 DRAFT Edukasi (auto, tiap 3 hari)\n"
            f"Topik: {topic}\n\n"
            f"{content.strip()}\n\n"
            "Tinggal copy-paste ke grup WA ya! "
            "(Atau ketik 'edit edukasi [instruksi]' untuk revisi)"
        )
