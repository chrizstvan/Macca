"""BaseChannelHandler-compatible wrapper around the Telegram Bot HTTP API.

The richer Telegram bot pipeline lives in :mod:`telegram_handler` (PTB +
webhook). This module exposes the same surface as
:class:`backend.channels.whatsapp_handler.WhatsAppHandler` so the channel
factory in ``base_handler.py`` can return either implementation, and so
outbound helpers (alerts, broadcasts) can reach Telegram without coupling
to the PTB Application object.

We deliberately call the Telegram HTTP API directly (via httpx) instead
of importing PTB here — that keeps this wrapper lightweight and avoids
double-wiring the Application instance.
"""

import logging
from typing import Any

import httpx

from backend.config import settings
from .base_handler import BaseChannelHandler

logger = logging.getLogger(__name__)

TELEGRAM_TEXT_MAX_LEN = 4096


def _api_base() -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}"


class TelegramHandler(BaseChannelHandler):
    """HTTP-only Telegram handler used by the channel factory."""

    async def handle_incoming(self, request_body: dict[str, Any]) -> None:
        """No-op: PTB owns the Telegram inbound pipeline at ``/webhook``.

        Kept as a stub so MultiChannelHandler can hold a TelegramHandler
        instance without the factory caller having to special-case channels.
        """
        return None

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
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                meta = await client.get(
                    f"{_api_base()}/getFile", params={"file_id": media_id}
                )
                meta.raise_for_status()
                file_path = (meta.json().get("result") or {}).get("file_path")
                if not file_path:
                    logger.error("Telegram getFile %s: missing file_path", media_id)
                    return None
                cdn = (
                    f"https://api.telegram.org/file/bot"
                    f"{settings.telegram_bot_token}/{file_path}"
                )
                resp = await client.get(cdn)
                resp.raise_for_status()
                return resp.content
        except httpx.HTTPError as exc:
            logger.error("Telegram download_media %s failed: %s", media_id, exc)
            return None

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
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{_api_base()}/{method}", json=payload)
                resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            body = None
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    body = response.text
                except Exception:
                    body = None
            logger.error("Telegram %s failed: %s — body: %s", method, exc, body)
            return False
