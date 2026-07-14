"""Quiz approval mixin: fasilitator reviews an auto-generated quiz draft.

The 3-day scheduler job parks a ``status='draft'`` row in ``quizzes`` and DMs
the fasilitator a review (answer shown). The fasilitator then replies:

* ``kirim quiz`` / ``kirim quiz 12 jam lagi`` / ``kirim quiz sekarang`` —
  approve + schedule (same ``ScheduleParser`` / ``scheduled_messages`` path as
  reminders). At send time the quiz becomes an ``active_quizzes`` row so
  answers feed ranking.
* ``edit quiz [instruksi]`` — regenerate the draft.
* ``batal quiz`` — discard.

Draft state is DB-backed (not pending_state) because approval may come hours
after the draft is generated — well past the 10-minute pending TTL.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_QUIZ_CMD_PATTERN = re.compile(r"\b(kirim|edit|batal)\s+quiz\b", re.IGNORECASE)


class QuizApprovalMixin:
    """Approve / edit / cancel an auto-generated quiz draft."""

    @classmethod
    def _is_quiz_command(cls, message: str) -> bool:
        return bool(message) and bool(_QUIZ_CMD_PATTERN.search(message))

    async def _handle_quiz_command(self, message: str, context: dict) -> str:
        from backend.infrastructure.composition_root import (
            build_quiz_draft_repository,
        )

        repo = build_quiz_draft_repository()
        try:
            draft = await repo.get_latest_draft()
        except Exception as exc:
            logger.warning("quiz draft lookup failed: %s", exc)
            return (
                "Gagal mengambil draft quiz (apakah tabel `quizzes` sudah ada?)."
            )
        if not draft:
            return "Tidak ada draft quiz yang menunggu persetujuan."

        match = _QUIZ_CMD_PATTERN.search(message)
        verb = match.group(1).lower()

        if verb == "batal":
            await repo.update_status(draft["id"], "cancelled")
            return "❌ Draft quiz dibatalkan."

        if verb == "edit":
            guidance = message[match.end():].strip() or None
            return await self._regenerate_quiz(repo, draft, guidance)

        # verb == "kirim" → approve + schedule / send.
        return await self._approve_and_schedule_quiz(repo, draft, message)

    async def _regenerate_quiz(self, repo, draft: dict, guidance: str | None) -> str:
        from backend.agents.quiz_generator import QuizGenerator

        generator = QuizGenerator()
        try:
            quiz = await generator.generate(guidance=guidance)
        except Exception as exc:
            logger.warning("quiz regenerate failed: %s", exc)
            return "Gagal membuat ulang quiz. Coba lagi."

        await repo.update(
            draft["id"],
            {
                "question": quiz["question"],
                "options": quiz["options"],
                "answer": quiz["answer"],
                "explanation": quiz["explanation"],
            },
        )
        return (
            generator.build_review_text(quiz)
            + "\n\nMau kirim? 'kirim quiz' / 'kirim quiz sekarang' / "
            "'edit quiz [instruksi]' / 'batal quiz'"
        )

    async def _approve_and_schedule_quiz(self, repo, draft: dict, message: str) -> str:
        from backend.infrastructure.composition_root import (
            build_broadcast_quiz_now,
            build_scheduled_message_repository,
        )
        from backend.utils.schedule_parser import ScheduleParser

        spec = {
            "question": draft.get("question", ""),
            "options": list(draft.get("options") or []),
            "answer": draft.get("answer", ""),
            "explanation": draft.get("explanation", ""),
        }
        schedule = await ScheduleParser(llm_caller=self.call_claude).parse_send_time(
            message
        )

        # Immediate — broadcast now + create the active_quizzes row.
        if schedule["mode"] == "immediate":
            try:
                result = await build_broadcast_quiz_now().execute(spec)
            except Exception as exc:
                logger.warning("quiz immediate broadcast failed: %s", exc)
                return f"Gagal mengirim quiz: {exc}"
            await repo.update_status(draft["id"], "sent")
            return (
                f"✅ Quiz dikirim sekarang ke {result.recipients_dispatched} "
                "volunteer! Jawaban dilacak untuk ranking (aktif 24 jam)."
            )

        # Otherwise — stash for the scheduled_messages dispatch job.
        try:
            await build_scheduled_message_repository().schedule_quiz(
                quiz=spec,
                recipient_filter="all",
                quiz_id=draft["id"],
                scheduled_at=schedule["send_at"],
                created_by="fasilitator_quiz",
            )
        except Exception as exc:
            logger.warning("scheduled quiz insert failed: %s", exc)
            return f"Gagal menjadwalkan quiz (tabel `scheduled_messages`?): {exc}"

        await repo.update_status(draft["id"], "approved")
        return (
            "✅ Quiz dijadwalkan!\n\n"
            f"📤 Akan dikirim {schedule['label']}\n"
            "👥 Ke semua volunteer\n\n"
            "Ubah? Ketik 'kirim quiz sekarang' atau 'batal quiz'."
        )
