"""Supabase-backed ChatHistoryRepository."""

from __future__ import annotations

from supabase import Client

from backend.application.ports.chat_history_repository import (
    ChatEntry,
    ChatHistoryRepository,
    ChatTurn,
    UserChatRow,
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

    async def list_recent_for(
        self, telegram_id: int | None, *, since_iso: str, limit: int = 20
    ) -> list[ChatEntry]:
        if not telegram_id:
            return []
        return (
            self._db.table("chat_history")
            .select("role, content, created_at")
            .eq("telegram_id", telegram_id)
            .gte("created_at", since_iso)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )

    async def all_user_messages(self) -> list[UserChatRow]:
        return (
            self._db.table("chat_history")
            .select("telegram_id, content")
            .eq("role", "user")
            .execute()
            .data
            or []
        )
