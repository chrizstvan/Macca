"""Cross-channel notification helpers.

Decoupled from the agent so the agent itself doesn't import a concrete
channel handler (DIP win).
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.utils.http_dispatcher import post_json

logger = logging.getLogger(__name__)


async def alert_fasilitator(text: str) -> None:
    """DM the fasilitator on Telegram (works outside PTB handlers too)."""
    if not settings.fasilitator_telegram_id or not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    await post_json(
        url,
        {"chat_id": settings.fasilitator_telegram_id, "text": text},
        log_label="notify.alert_fasilitator",
    )


async def notify_volunteer(volunteer: dict, text: str) -> None:
    """DM a target volunteer on whichever channel they're registered with.

    Picks WhatsApp first (since most volunteers run on it), falls back to
    Telegram if only the chat ID is on file.
    """
    phone = (volunteer or {}).get("phone")
    if phone:
        try:
            # Lazy import to avoid a circular dependency: WhatsAppHandler
            # lives in ``backend.channels`` which itself imports agent code.
            from backend.channels.whatsapp_handler import WhatsAppHandler

            await WhatsAppHandler().send_message(phone, text)
            return
        except Exception as exc:
            logger.error("Failed to notify volunteer on WhatsApp: %s", exc)

    telegram_id = (volunteer or {}).get("telegram_id")
    if telegram_id and settings.telegram_bot_token:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        await post_json(
            url,
            {"chat_id": telegram_id, "text": text},
            log_label="notify.notify_volunteer",
        )
