"""Quiz-draft generator agent.

LLM-generates a plastic/environment trivia quiz (question + labelled options +
answer + explanation) for the auto-generate-every-3-days flow. The draft is
reviewed by the fasilitator (answer shown) before any volunteer broadcast.

Parallels ``reminder_generator``: a thin presentation helper that only turns a
request into structured data. Persisting the draft and broadcasting live are
handled by the quiz-draft repository and the ``BroadcastQuizNow`` use case.
"""

from __future__ import annotations

import json
import logging
import re

from .base_agent import BaseAgent, COMPLEX_MODEL

logger = logging.getLogger(__name__)

_LETTERS = ["A", "B", "C", "D", "E", "F"]

_SYSTEM_PROMPT = (
    "Kamu adalah penulis quiz trivia plastik & lingkungan untuk volunteer "
    "Indonesia. Bahasa Indonesia santai. Jawaban harus akurat secara faktual."
)


class QuizGenerator(BaseAgent):
    """Generate a plastic-trivia quiz dict via Claude."""

    def __init__(self) -> None:
        super().__init__(
            name="quiz_generator",
            description="Generates plastic-trivia quiz drafts for fasilitator review.",
        )

    async def process(self, message: str, context: dict) -> str:
        """BaseAgent entry point — unused; the flow calls :meth:`generate`."""
        quiz = await self.generate()
        return self.build_review_text(quiz)

    async def generate(
        self,
        difficulty: str = "Sedang",
        num_options: int = 4,
        guidance: str | None = None,
    ) -> dict:
        """Return ``{question, options, answer, explanation}``.

        ``guidance`` carries an optional fasilitator edit instruction
        ("buat lebih susah", "fokus ke daur ulang") to bias regeneration.
        """
        num_options = max(2, min(int(num_options), 6))
        letters = _LETTERS[:num_options]
        user = (
            f"Buat 1 quiz trivia tingkat {difficulty} dengan {num_options} "
            f"pilihan jawaban berlabel {', '.join(letters)}. Balas HANYA JSON "
            "valid dengan kunci: question (string), options (list of strings, "
            "masing-masing dimulai dengan label + ') '), answer (single huruf), "
            "explanation (string, maks 25 kata)."
        )
        if guidance:
            user += f"\n\nInstruksi tambahan: {guidance}"

        raw = await self.call_claude(
            _SYSTEM_PROMPT,
            [{"role": "user", "content": user}],
            model=COMPLEX_MODEL,
            max_tokens=500,
        )

        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not match:
            raise ValueError("quiz model did not return JSON")
        data = json.loads(match.group(0))
        return {
            "question": data.get("question", ""),
            "options": list(data.get("options") or []),
            "answer": (data.get("answer") or "").strip().upper()[:1],
            "explanation": data.get("explanation", ""),
        }

    # ------------------------------------------------------------------ #
    # Formatting                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def format_options(options: list[str]) -> str:
        return "\n".join(options or [])

    @classmethod
    def build_review_text(cls, quiz: dict) -> str:
        """Fasilitator-facing review text — answer + explanation shown."""
        return (
            "🧠 Quiz Plastik (auto-generate)\n\n"
            f"{quiz.get('question', '')}\n\n"
            f"{cls.format_options(quiz.get('options') or [])}\n\n"
            f"✅ Jawaban: {quiz.get('answer', '')} — {quiz.get('explanation', '')}"
        )

    @staticmethod
    def build_volunteer_quiz_text(quiz: dict) -> str:
        """Volunteer-facing text — NO answer (they reply A/B/C/D)."""
        from backend.application.use_cases._plastic_content import (
            format_quiz_message,
        )

        return format_quiz_message(quiz)
