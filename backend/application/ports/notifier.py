"""Channel-aware notifier port.

Decouples use cases from the concrete WA/TG handlers. The adapter
delegates to ``backend.agents.services.notifications`` which already
applies the WA/TG priority rule based on ``settings.active_channel``.
"""

from __future__ import annotations

from typing import Protocol

from backend.domain.entities.volunteer import Volunteer


class Notifier(Protocol):
    async def notify_volunteer(self, volunteer: Volunteer, text: str) -> None: ...
    async def alert_fasilitator(self, text: str) -> None: ...
    async def broadcast(
        self, volunteers: list[Volunteer], text: str
    ) -> int:
        """Send ``text`` to each volunteer. Returns count of attempts dispatched."""

    async def broadcast_quiz(
        self, volunteers: list[Volunteer], quiz: dict, fallback_text: str
    ) -> int:
        """Send an interactive multiple-choice quiz.

        ``quiz`` is a ``QuizSpec``-shaped dict: ``{question, options, answer,
        explanation}``. Channels that support interactive lists (WhatsApp)
        render the choices as tappable rows; channels without that surface
        (Telegram) fall back to ``fallback_text``. Returns count of attempts
        dispatched.
        """
