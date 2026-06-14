"""Supabase-backed UnknownContactRepository."""

from __future__ import annotations

import logging

from supabase import Client

from backend.application.ports.unknown_contact_repository import (
    UnknownContactRepository,
)

logger = logging.getLogger(__name__)

_PREVIEW_MAX = 200


class SupabaseUnknownContactRepository(UnknownContactRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def record(self, *, phone: str, message_preview: str) -> None:
        try:
            self._db.table("unknown_contacts").insert(
                {
                    "phone": phone,
                    "message_preview": message_preview[:_PREVIEW_MAX],
                }
            ).execute()
        except Exception as exc:
            # Don't block the inbound pipeline if the table is missing yet.
            logger.warning("unknown_contacts insert failed: %s", exc)
