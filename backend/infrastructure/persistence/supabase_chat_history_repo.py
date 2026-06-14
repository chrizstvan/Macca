"""Supabase-backed ChatHistoryRepository."""

from __future__ import annotations

from supabase import Client

from backend.application.ports.chat_history_repository import (
    ChatHistoryRepository,
    ChatTurn,
)


class SupabaseChatHistoryRepository(ChatHistoryRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def get_recent(
        self, telegram_id: int | None, *, limit: int = 10
    ) -> list[ChatTurn]:
        if not telegram_id:
            return []
        rows = (
            self._db.table("chat_history")
            .select("role, content")
            .eq("telegram_id", telegram_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        # Oldest → newest so the LLM gets messages in conversational order.
        return [
            {"role": r["role"], "content": r["content"]} for r in reversed(rows)
        ]

    async def save_turn(
        self,
        telegram_id: int | None,
        *,
        role: str,
        content: str,
        agent_module: str,
    ) -> None:
        if not telegram_id:
            return
        self._db.table("chat_history").insert(
            {
                "telegram_id": telegram_id,
                "role": role,
                "content": content,
                "agent_module": agent_module,
            }
        ).execute()
