"""Fasilitator hub agent: orchestration + dispatch over the responsibility mixins."""

import logging

from backend.utils.query_utils import find_target_volunteer
from backend.utils.ranking_calculator import RankingCalculator

from ..base_agent import BaseAgent, COMPLEX_MODEL
from ..prompts.fasilitator_hub import STRATEGY_GUIDANCE, SYSTEM_PROMPT
from ._commands import CommandMixin
from ._constants import (
    DRAFT_PATTERN,
    LEADERBOARD_KEYWORDS,
    PSYCH_KEYWORDS,
    QA_PATTERN,
    REMIND_PATTERN,
    SEND_PATTERN,
    STRATEGY_KEYWORDS,
)
from ._consult import INVITE_CONFIRM_STEP, ConsultMixin
from ._election import ElectionMixin
from ._education import EducationDraftMixin
from ._ondemand import OnDemandDraftMixin
from ._queries import QueryMixin
from ._quiz import QuizApprovalMixin
from ._relay import RelayMixin
from ._reminders import REMINDER_DRAFT_STEP, ReminderMixin

logger = logging.getLogger(__name__)


class FasilitatorHubAgent(
    CommandMixin,
    ConsultMixin,
    RelayMixin,
    ReminderMixin,
    QuizApprovalMixin,
    EducationDraftMixin,
    OnDemandDraftMixin,
    ElectionMixin,
    QueryMixin,
    BaseAgent,
):
    """Operational summaries, flagged-report digests, broadcast drafting, and strategic consultation for fasilitators."""

    # Shared static used across mixins (process, psych/draft, query helpers).
    _find_target_by_name = staticmethod(find_target_volunteer)

    def __init__(self) -> None:
        super().__init__(
            name="fasilitator_hub",
            description="Operational tools and summaries for fasilitators",
        )

    async def process(self, message: str, context: dict) -> str:
        """Handle a fasilitator request; non-fasilitators are redirected politely."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        if not context["is_fasilitator"]:
            # Limited peer-query path — permitted by ALLOW_PEER_QUERY.
            if context.get("_limited_peer_query"):
                reply = await self.handle_volunteer_query(message, context)
                reply = self._append_suggestions(reply, "get_volunteer_detail")
                await self.save_chat_history(telegram_id, "user", message, self.name)
                await self.save_chat_history(telegram_id, "assistant", reply, self.name)
                return reply
            return (
                "This command is only available to the fasilitator. "
                "If you need help, just ask me a question directly!"
            )

        # Relay-save resume — if the fasilitator is in the middle of a
        # ``save_report_for`` flow waiting for a photo / 'no photo' reply,
        # short-circuit here BEFORE any other parse.
        from backend.agents.services import pending_state as _pending_state

        relay_key = _pending_state.pending_key(context)
        if relay_key and _pending_state.has_pending(relay_key):
            entry = _pending_state.store.get(relay_key) or {}
            if entry.get("step") == "fasilitator_relay_waiting_photo":
                reply = await self._resume_relay_save(
                    message=message, context=context, entry=entry
                )
                reply = self._append_suggestions(reply, "save_report_for")
                await self.save_chat_history(telegram_id, "user", message, self.name)
                await self.save_chat_history(telegram_id, "assistant", reply, self.name)
                return reply
            if entry.get("step") == REMINDER_DRAFT_STEP:
                reply = await self._resume_reminder_draft(
                    message=message, context=context, entry=entry
                )
                await self.save_chat_history(telegram_id, "user", message, self.name)
                await self.save_chat_history(telegram_id, "assistant", reply, self.name)
                return reply
            if entry.get("step") == INVITE_CONFIRM_STEP:
                reply = await self._resume_invite_send(
                    message=message, context=context, entry=entry
                )
                await self.save_chat_history(telegram_id, "user", message, self.name)
                await self.save_chat_history(telegram_id, "assistant", reply, self.name)
                return reply

        # Q&A relay — fasilitator forwards a volunteer question and (optionally)
        # asks the bot to DM the volunteer directly.
        stripped = message.strip()
        qa_match = QA_PATTERN.match(stripped)
        if qa_match:
            target_phone = qa_match.group(1)
            question = (qa_match.group(2) or "").strip()
            reply = await self._handle_qa(question, target_phone)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        send_match = SEND_PATTERN.match(stripped)
        if send_match:
            target_phone = send_match.group(1) or ""
            text_to_send = (send_match.group(2) or "").strip()
            reply = await self._handle_send(target_phone, text_to_send)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # /remind slash — bulk volunteer notifications.
        remind_match = REMIND_PATTERN.match(stripped)
        if remind_match:
            reply = await self._handle_remind_slash(
                subtype=(remind_match.group(1) or "").lower() or None,
                arg=(remind_match.group(2) or "").strip(),
            )
            reply = self._append_suggestions(reply, "send_reminder")
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # Capture project-context updates before anything else — single-turn
        # acknowledgement, no Claude call needed.
        captured = await self._capture_project_context(message)
        if captured is not None:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", captured, self.name)
            return captured

        # Quiz approval — fasilitator replying to an auto-generated quiz draft
        # ("kirim quiz" / "edit quiz …" / "batal quiz"). Intercept early.
        if self._is_quiz_command(message):
            reply = await self._handle_quiz_command(message, context)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # Education draft revision ("edit edukasi [instruksi]").
        if self._is_education_edit(message):
            reply = await self._handle_education_edit(message, context)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # On-demand DRAFT requests ("buatkan checklist/laporan impact/edukasi …").
        # Intercept before intent classification (would otherwise hit
        # generate_report / generate_content). Draft-only, never broadcast.
        if self._ondemand_draft_kind(message):
            reply = await self._handle_ondemand_draft(message, context)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # Election flow — check confirm ("ya mulai pencalonan X") before start
        # ("mulai pemilihan …"), both before intent classification.
        if self._is_election_confirm(message):
            reply = await self._handle_election_confirm(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        if self._is_election_start(message):
            reply = await self._handle_election_start(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        if self._is_election_close(message):
            reply = await self._handle_election_close(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        if self._is_election_voting(message):
            reply = await self._handle_election_voting(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        if self._is_election_close_vote(message):
            reply = await self._handle_election_close_vote(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        if self._is_election_finalize(message):
            reply = await self._handle_election_finalize(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        if self._is_election_announce(message):
            reply = await self._handle_election_announce(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        if self._is_election_status(message):
            reply = await self._handle_election_status(message)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # Action-item reminder flow — intercept BEFORE intent classification so
        # "buatkan reminder presensi" isn't swallowed by the generic
        # ``send_reminder`` progress-nudge intent.
        if self._is_reminder_request(message):
            reply = await self._handle_reminder_request(message, context)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # Natural-language invite → draft + confirm + WhatsApp send.
        # Intercept before intent classification (would otherwise be swallowed
        # by generate_content / send_reminder). Returns None when no known
        # volunteer is named → fall through to the normal pipeline.
        if self._is_invite_request(message):
            invite_reply = await self._handle_invite_request(message, context)
            if invite_reply is not None:
                await self.save_chat_history(telegram_id, "user", message, self.name)
                await self.save_chat_history(telegram_id, "assistant", invite_reply, self.name)
                return invite_reply

        # Phase 6 intent classification — dispatch dedicated handlers BEFORE the
        # legacy strategy/psych/draft fallback.
        try:
            intent = await self._classify_command(message)
        except Exception as exc:
            logger.warning("intent classify failed: %s", exc)
            intent = "default"

        if intent != "default":
            try:
                reply = await self._dispatch_intent(intent, message, context)
            except Exception as exc:
                logger.exception("intent handler %s crashed: %s", intent, exc)
                reply = "Maaf, ada error saat menjalankan perintah itu. Coba ulangi atau ketik permintaan lain."
            reply = self._append_suggestions(reply, intent)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        lowered = message.lower()
        is_strategy = any(kw in lowered for kw in STRATEGY_KEYWORDS)
        is_psych = any(kw in lowered for kw in PSYCH_KEYWORDS)
        draft_match = DRAFT_PATTERN.search(message)

        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        volunteers = await build_volunteer_query_repository().list_all()

        # Draft path takes priority — fasilitator already accepted the offer
        # to draft a personalised message.
        if draft_match:
            target = self._find_target_by_name(message, volunteers)
            reply = await self._handle_draft_message(target)
            reply = self._append_suggestions(reply, "default")
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        if is_psych:
            target = self._find_target_by_name(message, volunteers)
            reply = await self._handle_psych_guidance(message, target, telegram_id)
            reply = self._append_suggestions(reply, "default")
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        from backend.infrastructure.composition_root import (
            build_report_repository,
        )

        flagged = [
            {
                "kg_collected": r.kg_collected.value,
                "location": r.location,
                "flag_reason": r.flag_reason,
                "reported_at": r.reported_at.isoformat() if r.reported_at else None,
            }
            for r in await build_report_repository().list_flagged_unverified()
        ]
        extra = (
            f"\n\nVolunteers ({len(volunteers)}): {volunteers}"
            f"\nUnverified flagged reports ({len(flagged)}): {flagged}"
        )

        if any(kw in message.lower() for kw in LEADERBOARD_KEYWORDS):
            leaderboard = await RankingCalculator().get_leaderboard(limit=10)
            if leaderboard:
                extra += f"\n\nLeaderboard (top {len(leaderboard)}): {leaderboard}"
            else:
                extra += "\n\nLeaderboard: belum tersedia (jalankan update ranking)."

        if is_strategy:
            strategy_block = await self._build_strategy_block(volunteers, telegram_id)
            extra += strategy_block

        system_prompt = SYSTEM_PROMPT + (STRATEGY_GUIDANCE if is_strategy else "")
        # Sonnet for strategy consultations (quality matters); Haiku otherwise.
        model = COMPLEX_MODEL if is_strategy else "claude-haiku-4-5-20251001"

        history = await self.get_chat_history(telegram_id)
        messages = history + [{"role": "user", "content": message}]

        reply = await self.call_claude(system_prompt + extra, messages, model=model, max_tokens=2000)
        reply = self._append_suggestions(reply, "default")
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply
