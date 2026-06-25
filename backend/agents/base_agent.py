"""Abstract base agent with shared Claude API and Supabase helpers."""

import logging
from abc import ABC, abstractmethod
from typing import Any

import anthropic

from backend.config import settings
from backend.utils.phone_utils import normalize_phone

logger = logging.getLogger(__name__)

# Snapshot at import time — overridable via env vars CLAUDE_DEFAULT_MODEL /
# CLAUDE_COMPLEX_MODEL. See ``backend.config`` for defaults.
DEFAULT_MODEL = settings.claude_default_model
COMPLEX_MODEL = settings.claude_complex_model

FALLBACK_MESSAGE = (
    "Sorry, I'm having trouble processing your message right now. "
    "Please try again in a moment, or contact your fasilitator if the problem persists."
)


class BaseAgent(ABC):
    """Base class for all Macca agents.

    Provides a shared Anthropic client, Claude call helper with error
    handling and token logging, and Supabase helpers for chat history
    and volunteer lookups. Subclasses implement ``process``.
    """

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    @abstractmethod
    async def process(self, message: str, context: dict) -> str:
        """Process an incoming message and return the reply text."""

    async def call_claude(
        self,
        system_prompt: str,
        messages: list,
        model: str = DEFAULT_MODEL,
        max_tokens: int | None = None,
    ) -> str:
        """Call Claude and return the response text.

        Uses the configured default model (Haiku) for cost efficiency;
        pass ``model=COMPLEX_MODEL`` for complex tasks. ``max_tokens``
        defaults to ``settings.default_max_tokens`` when omitted.
        Returns a friendly fallback message on API errors.
        """
        if max_tokens is None:
            max_tokens = settings.default_max_tokens
        try:
            response = await self.anthropic_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
            logger.info(
                "[%s] %s tokens — input: %d, output: %d",
                self.name,
                model,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            return response.content[0].text
        except anthropic.APIError as exc:
            logger.error("[%s] Claude API error: %s", self.name, exc)
            return FALLBACK_MESSAGE

    async def get_chat_history(
        self, telegram_id: int | None, limit: int = 10
    ) -> list:
        """Fetch the last ``limit`` messages for a user, oldest first.

        Delegates to ``ChatHistoryRepository`` via the composition root.
        Returns ``[]`` when ``telegram_id`` is falsy (e.g. WhatsApp users —
        the chat_history table is keyed by Telegram bigint and has no phone
        column yet, so we skip persistence for non-Telegram channels until
        a schema update lands).
        """
        from backend.infrastructure.composition_root import (
            build_chat_history_repository,
        )

        return await build_chat_history_repository().get_recent(
            telegram_id, limit=limit
        )

    async def save_chat_history(
        self,
        telegram_id: int | None,
        role: str,
        content: str,
        agent_module: str,
    ) -> None:
        """Persist a single message to the chat_history table.

        Delegates to ``ChatHistoryRepository``. No-op when ``telegram_id``
        is falsy — see get_chat_history for why.
        """
        from backend.infrastructure.composition_root import (
            build_chat_history_repository,
        )

        await build_chat_history_repository().save_turn(
            telegram_id, role=role, content=content, agent_module=agent_module
        )

    async def get_volunteer(self, telegram_id: int) -> dict[str, Any] | None:
        """Fetch a volunteer profile by Telegram ID, or None if not registered."""
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        return await build_volunteer_query_repository().get_by_telegram_id(
            telegram_id
        )

    # Thin alias preserved for back-compat with subclasses that still call
    # ``self._normalize_phone``; the canonical implementation now lives in
    # ``backend.utils.phone_utils.normalize_phone``.
    _normalize_phone = staticmethod(normalize_phone)

    async def get_volunteer_by_phone(self, phone: str) -> dict[str, Any] | None:
        """Fetch a volunteer by phone (normalised), or None if not registered."""
        normalized = normalize_phone(phone)
        if not normalized:
            return None
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        return await build_volunteer_query_repository().get_by_phone(normalized)

    async def get_volunteer_flexible(self, context: dict) -> dict[str, Any] | None:
        """Look up a volunteer by phone (WhatsApp) first, then telegram_id.

        Returns the first match found, or None if neither identifier resolves.
        """
        sender_phone = context.get("sender_phone")
        if sender_phone:
            volunteer = await self.get_volunteer_by_phone(sender_phone)
            if volunteer:
                return volunteer

        telegram_id = context.get("telegram_id")
        if telegram_id:
            volunteer = await self.get_volunteer(telegram_id)
            if volunteer:
                return volunteer

        return None

    def is_fasilitator(self, context: dict) -> bool:
        """True if the message sender is the fasilitator on either channel."""
        sender_phone = normalize_phone(context.get("sender_phone"))
        fasilitator_phone = normalize_phone(settings.fasilitator_phone)
        if sender_phone and fasilitator_phone and sender_phone == fasilitator_phone:
            return True

        telegram_id = context.get("telegram_id")
        if (
            telegram_id
            and settings.fasilitator_telegram_id
            and telegram_id == settings.fasilitator_telegram_id
        ):
            return True

        return False

    def build_context_flags(self, context: dict) -> dict:
        """Attach derived flags (is_fasilitator, is_test_mode, channel) to context."""
        context["is_fasilitator"] = self.is_fasilitator(context)
        context["is_test_mode"] = context.get("test_volunteer_id") is not None
        context["channel"] = context.get("channel", "telegram")
        return context
