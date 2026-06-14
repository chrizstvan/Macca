"""Anthropic-backed LLMClient adapter."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from backend.application.ports.llm_client import LLMClient

logger = logging.getLogger(__name__)

_FALLBACK = (
    "Sorry, I'm having trouble processing your message right now. "
    "Please try again in a moment."
)


class AnthropicLLMClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        *,
        default_model: str,
        default_max_tokens: int = 1000,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        if max_tokens is None:
            max_tokens = self._default_max_tokens
        chosen_model = model or self._default_model
        try:
            resp = await self._client.messages.create(
                model=chosen_model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            logger.info(
                "[llm] %s tokens — input: %d, output: %d",
                chosen_model,
                resp.usage.input_tokens,
                resp.usage.output_tokens,
            )
            return resp.content[0].text
        except anthropic.APIError as exc:
            logger.error("[llm] Anthropic API error: %s", exc)
            return _FALLBACK
