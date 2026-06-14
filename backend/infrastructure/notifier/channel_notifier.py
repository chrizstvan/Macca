"""Notifier adapter wrapping ``services.notifications``."""

from __future__ import annotations

from backend.application.ports.notifier import Notifier
from backend.domain.entities.volunteer import Volunteer

# Lazy-import the agent-layer services inside methods to avoid a circular
# dependency: notifications.py imports the channel handlers, which in turn
# import use cases via main.py.


class ChannelNotifier(Notifier):
    async def notify_volunteer(self, volunteer: Volunteer, text: str) -> None:
        from backend.agents.services.notifications import notify_volunteer

        await notify_volunteer(self._to_dict(volunteer), text)

    async def alert_fasilitator(self, text: str) -> None:
        from backend.agents.services.notifications import alert_fasilitator

        await alert_fasilitator(text)

    async def broadcast(
        self, volunteers: list[Volunteer], text: str
    ) -> int:
        from backend.agents.services.notifications import notify_volunteer

        dispatched = 0
        for v in volunteers:
            await notify_volunteer(self._to_dict(v), text)
            dispatched += 1
        return dispatched

    @staticmethod
    def _to_dict(volunteer: Volunteer) -> dict:
        return {
            "phone": volunteer.phone.value if volunteer.phone else None,
            "telegram_id": volunteer.telegram_id,
            "name": volunteer.name,
        }
