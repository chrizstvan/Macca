"""Tracks inbound messages from phone numbers not yet registered as volunteers."""

from __future__ import annotations

from typing import Protocol


class UnknownContactRepository(Protocol):
    async def record(self, *, phone: str, message_preview: str) -> None:
        """Persist a row in ``unknown_contacts`` so the fasilitator can triage."""
