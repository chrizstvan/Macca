"""Abstract base agent with shared Claude API and Supabase helpers."""

import logging
from abc import ABC, abstractmethod
from typing import Any

import anthropic

from backend.config import settings
from backend.database.supabase_client import db

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # cost-efficient default
COMPLEX_MODEL = "claude-sonnet-4-6"  # override for complex tasks

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
        max_tokens: int = 1000,
    ) -> str:
        """Call Claude and return the response text.

        Uses claude-haiku-4-5 by default for cost efficiency; pass
        ``model=COMPLEX_MODEL`` (claude-sonnet-4-6) for complex tasks.
        Returns a friendly fallback message on API errors.
        """
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

    async def get_chat_history(self, telegram_id: int, limit: int = 10) -> list:
        """Fetch the last ``limit`` messages for a user, oldest first.

        Returns a list of ``{"role": "user"|"assistant", "content": str}``
        dicts ready to pass to the Claude messages API.
        """
        result = (
            db.table("chat_history")
            .select("role, content")
            .eq("telegram_id", telegram_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data or []
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    async def save_chat_history(
        self, telegram_id: int, role: str, content: str, agent_module: str
    ) -> None:
        """Persist a single message to the chat_history table."""
        db.table("chat_history").insert(
            {
                "telegram_id": telegram_id,
                "role": role,
                "content": content,
                "agent_module": agent_module,
            }
        ).execute()

    async def get_volunteer(self, telegram_id: int) -> dict[str, Any] | None:
        """Fetch a volunteer profile by Telegram ID, or None if not registered."""
        result = (
            db.table("volunteers")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Normalize to digits-only Indonesian E.164 (62xxxxxxxxx).

        Strips '+', spaces, hyphens, and parentheses; rewrites a leading
        '08' to '628'. Returns empty string if input is empty/None.
        """
        if not phone:
            return ""
        cleaned = (
            phone.strip()
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        if cleaned.startswith("08"):
            cleaned = "62" + cleaned[1:]
        return cleaned

    async def get_volunteer_by_phone(self, phone: str) -> dict[str, Any] | None:
        """Fetch a volunteer by phone (normalised), or None if not registered."""
        normalized = self._normalize_phone(phone)
        if not normalized:
            return None
        result = (
            db.table("volunteers")
            .select("*")
            .eq("phone", normalized)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

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
        sender_phone = self._normalize_phone(context.get("sender_phone") or "")
        fasilitator_phone = self._normalize_phone(settings.fasilitator_phone)
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
