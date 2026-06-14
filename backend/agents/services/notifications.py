"""Cross-channel notification helpers.

Decoupled from the agent so the agent itself doesn't import a concrete
channel handler (DIP win).

Channel priority (matches ``ACTIVE_CHANNEL=whatsapp`` rollout):

* WhatsApp first, when target identity + WA credentials are available.
* Telegram fallback when WA fails / isn't applicable / credentials missing.

The helpers return silently on success; failures are logged but never
raised so a single bad outbound never crashes the agent pipeline.
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.utils.http_dispatcher import post_json
from backend.utils.phone_utils import normalize_phone

logger = logging.getLogger(__name__)


def _wa_credentials_ready() -> bool:
    return bool(
        settings.whatsapp_phone_number_id and settings.whatsapp_access_token
    )


async def _send_whatsapp(to_phone: str, text: str, *, log_label: str) -> bool:
    """Try to deliver via WhatsApp Cloud API. Returns True on 2xx."""
    phone = normalize_phone(to_phone)
    if not phone or not _wa_credentials_ready():
        return False
    try:
        # Lazy import: backend.channels imports agent code, so importing it
        # at module level would create a cycle.
        from backend.channels.whatsapp_handler import WhatsAppHandler

        return await WhatsAppHandler().send_message(phone, text)
    except Exception as exc:
        logger.error("%s: WhatsApp send failed: %s", log_label, exc)
        return False


async def _send_telegram(chat_id: int, text: str, *, log_label: str) -> bool:
    if not chat_id or not settings.telegram_bot_token:
        return False
    url = (
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    )
    ok, _body = await post_json(
        url, {"chat_id": chat_id, "text": text}, log_label=log_label
    )
    return ok


def _channel_priority() -> list[str]:
    """Order channels to try based on ``settings.active_channel``.

    ``telegram`` → TG first, WA fallback.
    ``whatsapp`` / ``both`` → WA first, TG fallback.
    """
    if settings.active_channel == "telegram":
        return ["telegram", "whatsapp"]
    return ["whatsapp", "telegram"]


async def alert_fasilitator(text: str) -> None:
    """DM the fasilitator on the active channel; fall back to the other."""
    for channel in _channel_priority():
        if channel == "whatsapp":
            if await _send_whatsapp(
                settings.fasilitator_phone,
                text,
                log_label="notify.alert_fasilitator.wa",
            ):
                return
        else:
            if await _send_telegram(
                settings.fasilitator_telegram_id,
                text,
                log_label="notify.alert_fasilitator.tg",
            ):
                return


async def notify_volunteer(volunteer: dict, text: str) -> None:
    """DM a volunteer on the active channel; fall back to the other."""
    phone = (volunteer or {}).get("phone")
    telegram_id = (volunteer or {}).get("telegram_id")
    for channel in _channel_priority():
        if channel == "whatsapp" and phone:
            if await _send_whatsapp(
                phone, text, log_label="notify.notify_volunteer.wa"
            ):
                return
        elif channel == "telegram" and telegram_id:
            if await _send_telegram(
                telegram_id, text, log_label="notify.notify_volunteer.tg"
            ):
                return
