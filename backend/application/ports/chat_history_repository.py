"""Read/write port for chat_history.

Currently keyed by Telegram chat_id (bigint column in Supabase). Calls
with ``telegram_id is None`` should no-op so WhatsApp-only volunteers
don't break the use cases.
"""

from __future__ import annotations

from typing import Protocol, TypedDict


class ChatTurn(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class ChatHistoryRepository(Protocol):
    async def get_recent(
        self, telegram_id: int | None, *, limit: int = 10
    ) -> list[ChatTurn]: ...

    async def save_turn(
        self,
        telegram_id: int | None,
        *,
        role: str,
        content: str,
        agent_module: str,
    ) -> None: ...
