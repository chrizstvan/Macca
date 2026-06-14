"""Outbound-only wrapper around the Telegram Bot HTTP API.

The richer Telegram bot pipeline lives in :mod:`telegram_handler` (PTB +
webhook); that module owns the *inbound* surface. This module exposes
just the :class:`OutboundSender` interface so the channel factory can
return a uniform "thing you can send with" regardless of which channel
is active.

We deliberately call the Telegram HTTP API directly (via httpx) instead
of importing PTB here — that keeps this wrapper lightweight and avoids
double-wiring the Application instance.
"""

import logging
from typing import Any

from backend.config import settings
from backend.utils.http_dispatcher import get_bytes, get_json, post_json
from .base_handler import OutboundSender

logger = logging.getLogger(__name__)

TELEGRAM_TEXT_MAX_LEN = 4096


def _api_base() -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}"


class TelegramHandler(OutboundSender):
    """Outbound-only Telegram handler used by the channel factory.

    Inbound dispatch is owned by :mod:`telegram_handler` (PTB application).
    This class doesn't implement :class:`InboundReceiver` because it would
    only ever return ``None`` — see Pass D notes in ``base_handler``.
    """

    async def send_message(self, to: str, text: str) -> bool:
        return await self._post(
            "sendMessage",
            {"chat_id": to, "text": text[:TELEGRAM_TEXT_MAX_LEN]},
        )

    async def send_image(self, to: str, image_url: str, caption: str = "") -> bool:
        payload: dict[str, Any] = {"chat_id": to, "photo": image_url}
        if caption:
            payload["caption"] = caption[:1024]
        return await self._post("sendPhoto", payload)

    async def send_buttons(
        self, to: str, body_text: str, buttons: list[str]
    ) -> bool:
        if not buttons:
            return await self.send_message(to, body_text)
        keyboard = [
            [{"text": label, "callback_data": f"btn_{idx}"}]
            for idx, label in enumerate(buttons)
        ]
        return await self._post(
            "sendMessage",
            {
                "chat_id": to,
                "text": body_text[:TELEGRAM_TEXT_MAX_LEN],
                "reply_markup": {"inline_keyboard": keyboard},
            },
        )

    async def send_read_receipt(self, to: str, message_id: str) -> None:
        # Telegram has no per-message "mark as read" API for bots.
        return None

    async def download_media(self, media_id: str) -> bytes | None:
        """Resolve a Telegram file_id to bytes via getFile + CDN download."""
        if not media_id:
            return None
        ok, body = await get_json(
            f"{_api_base()}/getFile",
            params={"file_id": media_id},
            timeout=30,
            log_label="telegram.getFile",
        )
        if not ok or not body:
            return None
        file_path = (body.get("result") or {}).get("file_path")
        if not file_path:
            logger.error("Telegram getFile %s: missing file_path", media_id)
            return None
        cdn = (
            f"https://api.telegram.org/file/bot"
            f"{settings.telegram_bot_token}/{file_path}"
        )
        return await get_bytes(cdn, timeout=30, log_label="telegram.cdn")

    async def send_alert(self, text: str) -> None:
        if not settings.fasilitator_telegram_id:
            logger.warning("Telegram send_alert: fasilitator_telegram_id not configured")
            return
        await self.send_message(str(settings.fasilitator_telegram_id), f"🚨 ALERT: {text}")

    def is_fasilitator(self, sender_id: str) -> bool:
        if not settings.fasilitator_telegram_id:
            return False
        try:
            return int(sender_id) == settings.fasilitator_telegram_id
        except (TypeError, ValueError):
            return False

    async def _post(self, method: str, payload: dict[str, Any]) -> bool:
        if not settings.telegram_bot_token:
            logger.error("Telegram bot token not configured")
            return False
        ok, _body = await post_json(
            f"{_api_base()}/{method}",
            payload,
            log_label=f"telegram.{method}",
        )
        return ok
