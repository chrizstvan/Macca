"""Read/write port for the ``content_drafts`` table.

Stores draft-only fasilitator content (e.g. ``type='education'`` group posts)
that is never auto-broadcast — the fasilitator copy-pastes it manually. Editable
until they use it; no approval/scheduling lifecycle (unlike quizzes).
"""

from __future__ import annotations

from typing import Protocol


class ContentDraftRepository(Protocol):
    async def create_draft(
        self, *, type: str, topic: str, content: str
    ) -> str:
        """Insert a content draft; return its id."""

    async def get_latest_draft(self, type: str) -> dict | None:
        """Most recent draft of ``type``, or None."""

    async def update(self, draft_id: str, fields: dict) -> None:
        """Patch columns on a draft row."""
