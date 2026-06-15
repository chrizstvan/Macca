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

    async def broadcast_quiz(
        self, volunteers: list[Volunteer], quiz: dict, fallback_text: str
    ) -> int:
        """Send WA list message per volunteer; fall back to text on WA failure / TG."""
        from backend.agents.services.notifications import (
            _send_telegram,
            _wa_credentials_ready,
        )
        from backend.config import settings
        from backend.channels.whatsapp_handler import WhatsAppHandler

        wa_ready = _wa_credentials_ready()
        wa_first = settings.active_channel in {"whatsapp", "both"}
        wa_handler = WhatsAppHandler() if wa_ready else None

        dispatched = 0
        for v in volunteers:
            vdict = self._to_dict(v)
            phone = vdict.get("phone")
            telegram_id = vdict.get("telegram_id")
            delivered = False

            if wa_first and wa_handler and phone:
                try:
                    delivered = await wa_handler.send_quiz(phone, quiz)
                except Exception:
                    delivered = False

            if not delivered and telegram_id:
                delivered = await _send_telegram(
                    telegram_id,
                    fallback_text,
                    log_label="notify.broadcast_quiz.tg",
                )

            # WA-first failed and no TG → retry plain WA text as last resort.
            if not delivered and wa_handler and phone:
                try:
                    delivered = await wa_handler.send_message(
                        phone, fallback_text
                    )
                except Exception:
                    delivered = False

            if delivered:
                dispatched += 1
        return dispatched

    @staticmethod
    def _to_dict(volunteer: Volunteer) -> dict:
        return {
            "phone": volunteer.phone.value if volunteer.phone else None,
            "telegram_id": volunteer.telegram_id,
            "name": volunteer.name,
        }
