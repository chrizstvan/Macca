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
