"""Base agent class providing shared Claude API interaction for all agents."""

from abc import ABC, abstractmethod
from typing import Any

import anthropic

from backend.config import config


class BaseAgent(ABC):
    """Abstract base for all Macca agents.

    Subclasses define their system prompt and implement `handle`, which
    receives a user message and optional context, calls Claude, and returns
    a structured response.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt that defines this agent's role and behaviour."""

    @abstractmethod
    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process an incoming message and return a structured response."""

    def _call_claude(self, user_message: str, extra_system: str = "") -> str:
        """Send a message to Claude and return the text content of the response."""
        system = self.system_prompt
        if extra_system:
            system = f"{system}\n\n{extra_system}"

        response = self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=config.MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
