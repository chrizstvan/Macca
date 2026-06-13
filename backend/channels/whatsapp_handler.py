"""WhatsApp Cloud API channel handler.

Parses inbound webhook payloads from Meta, dispatches them through the
agent router, sends replies back via the Graph API, and offers helper
methods for images, interactive buttons, read receipts, media download,
and fasilitator alerts.
"""

import logging
import re
from typing import Any

import httpx

from backend.config import settings
from backend.utils.image_handler import ImageHandler
from .base_handler import BaseChannelHandler

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v18.0"
WA_TEXT_MAX_LEN = 4096
WA_BUTTON_TITLE_MAX_LEN = 20


class WhatsAppHandler(BaseChannelHandler):
    """Inbound + outbound message handler for WhatsApp Cloud API."""

    def __init__(
        self,
        router: Any = None,
        image_handler: ImageHandler | None = None,
    ) -> None:
        # ``router`` is duck-typed (RouterAgent) — wired by the app on startup.
        self.router = router
        self.image_handler = image_handler or ImageHandler()

    # ------------------------------------------------------------------ #
    # Inbound                                                            #
    # ------------------------------------------------------------------ #

    async def handle_incoming(self, request_body: dict[str, Any]) -> None:
        """Parse a webhook payload, dispatch through the router, send reply."""
        ctx = await self._parse_payload(request_body)
        if not ctx:
            return

        sender_phone = ctx.get("sender_phone")
        wa_message_id = ctx.get("wa_message_id")

        # Best-effort read receipt — never block dispatch if it fails.
        if sender_phone and wa_message_id:
            try:
                await self.send_read_receipt(sender_phone, wa_message_id)
            except Exception as exc:
                logger.warning("WhatsApp read receipt failed: %s", exc)

        if self.router is None:
            logger.warning("WhatsApp router not wired — dropping message")
            return

        text = ctx.get("message") or ""
        if not text:
            return

        try:
            reply = await self.router.route(text, ctx)
        except Exception as exc:
            logger.exception("WhatsApp router dispatch failed: %s", exc)
            return

        if reply and sender_phone:
            await self.send_message(sender_phone, reply)

    async def _parse_payload(
        self, request_body: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Normalise a Meta webhook payload into a single-message context dict.

        Returns ``None`` for status-only events (delivered/read/sent) so the
        caller can short-circuit without dispatching anything.
        """
        try:
            change = request_body["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError, TypeError):
            logger.warning("WhatsApp payload missing entry/changes: %r", request_body)
            return None

        messages = change.get("messages") or []
        if not messages:
            return None

        message = messages[0]
        sender_phone = message.get("from", "")
        message_type = message.get("type")
        text = ""
        photo_url: str | None = None

        if message_type == "text":
            text = (message.get("text") or {}).get("body", "")
        elif message_type == "image":
            image = message.get("image") or {}
            media_id = image.get("id")
            text = image.get("caption") or "laporan foto"
            if media_id and settings.whatsapp_access_token:
                photo_url = await self.image_handler.upload_from_whatsapp(
                    media_id, settings.whatsapp_access_token, sender_phone
                )
        elif message_type == "interactive":
            interactive = message.get("interactive") or {}
            reply = (interactive.get("button_reply") or interactive.get("list_reply") or {})
            text = reply.get("title") or reply.get("id") or ""
        else:
            text = f"[{message_type} message — belum didukung]"

        return {
            "channel": "whatsapp",
            "sender_phone": sender_phone,
            "wa_message_id": message.get("id"),
            "message": text,
            "photo_url": photo_url,
            "chat_type": "private",
        }

    # ------------------------------------------------------------------ #
    # Outbound — text / image / buttons                                   #
    # ------------------------------------------------------------------ #

    async def send_message(self, to: str, text: str) -> bool:
        """POST a text message to the WhatsApp Cloud API."""
        if not self._creds_ready():
            return False
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": self._to_whatsapp_markdown(text)[:WA_TEXT_MAX_LEN]},
        }
        return await self._post_messages(payload)

    async def send_image(
        self, to: str, image_url: str, caption: str = ""
    ) -> bool:
        """POST an image message (by URL) to the WhatsApp Cloud API."""
        if not self._creds_ready():
            return False
        image: dict[str, Any] = {"link": image_url}
        if caption:
            image["caption"] = self._to_whatsapp_markdown(caption)
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": image,
        }
        return await self._post_messages(payload)

    async def send_buttons(
        self, to: str, body_text: str, buttons: list[str]
    ) -> bool:
        """Send an interactive reply-button message (max 3 buttons)."""
        if not self._creds_ready():
            return False
        if not buttons:
            return await self.send_message(to, body_text)
        if len(buttons) > 3:
            logger.warning("WhatsApp allows max 3 buttons; truncating from %d", len(buttons))
        button_objects = [
            {
                "type": "reply",
                "reply": {
                    "id": f"btn_{idx}",
                    "title": label[:WA_BUTTON_TITLE_MAX_LEN],
                },
            }
            for idx, label in enumerate(buttons[:3])
        ]
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": self._to_whatsapp_markdown(body_text)[:1024]},
                "action": {"buttons": button_objects},
            },
        }
        return await self._post_messages(payload)

    # ------------------------------------------------------------------ #
    # Read receipts                                                       #
    # ------------------------------------------------------------------ #

    async def send_read_receipt(self, to: str, message_id: str) -> None:
        """Mark an inbound WhatsApp message as read.

        ``to`` is included to satisfy the BaseChannelHandler signature but is
        not used by the Graph API — ``message_id`` alone identifies the chat.
        """
        if not self._creds_ready() or not message_id:
            return
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        await self._post_messages(payload)

    # ------------------------------------------------------------------ #
    # Media download (raw bytes)                                          #
    # ------------------------------------------------------------------ #

    async def download_media(self, media_id: str) -> bytes | None:
        """Resolve a Graph media_id to a signed URL and return the bytes."""
        if not settings.whatsapp_access_token or not media_id:
            return None
        headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                meta_resp = await client.get(
                    f"{GRAPH_BASE}/{media_id}", headers=headers
                )
                meta_resp.raise_for_status()
                media_url = meta_resp.json().get("url")
                if not media_url:
                    logger.error("WhatsApp media %s: missing 'url' in metadata", media_id)
                    return None
                bin_resp = await client.get(media_url, headers=headers)
                bin_resp.raise_for_status()
                return bin_resp.content
        except httpx.HTTPError as exc:
            logger.error("WhatsApp download_media %s failed: %s", media_id, exc)
            return None

    # ------------------------------------------------------------------ #
    # Fasilitator alert                                                   #
    # ------------------------------------------------------------------ #

    async def send_alert(self, text: str) -> None:
        """DM the fasilitator at ``settings.fasilitator_phone``."""
        phone = self._normalize_phone(settings.fasilitator_phone)
        if not phone:
            logger.warning("WhatsApp send_alert: fasilitator_phone not configured")
            return
        await self.send_message(phone, f"🚨 ALERT: {text}")

    # ------------------------------------------------------------------ #
    # Identity                                                            #
    # ------------------------------------------------------------------ #

    def is_fasilitator(self, sender_id: str) -> bool:
        """True if ``sender_id`` (phone) matches the configured fasilitator."""
        sender = self._normalize_phone(sender_id)
        fasilitator = self._normalize_phone(settings.fasilitator_phone)
        return bool(sender and fasilitator and sender == fasilitator)

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _creds_ready(self) -> bool:
        if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
            logger.error("WhatsApp credentials missing — cannot call Graph API")
            return False
        return True

    async def _post_messages(self, payload: dict[str, Any]) -> bool:
        url = f"{GRAPH_BASE}/{settings.whatsapp_phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
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
            logger.error("WhatsApp send failed: %s — body: %s", exc, body)
            return False

    @staticmethod
    def _to_whatsapp_markdown(text: str) -> str:
        """Rewrite common Markdown/HTML formatting into WhatsApp's syntax.

        Telegram-flavoured HTML (``<b>``, ``<i>``, ``<code>``) and CommonMark
        (``**bold**``, ``__italic__``) are normalised to WhatsApp's wire
        format: ``*bold*``, ``_italic_``, ``~strike~``, `` `code` ``.
        Any other tags are stripped so they don't show up as literal text.
        """
        if not text:
            return ""
        converted = text
        # HTML → WA
        converted = re.sub(r"<\s*(b|strong)\s*>(.*?)<\s*/\s*\1\s*>", r"*\2*", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*(i|em)\s*>(.*?)<\s*/\s*\1\s*>", r"_\2_", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*(s|strike|del)\s*>(.*?)<\s*/\s*\1\s*>", r"~\2~", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*code\s*>(.*?)<\s*/\s*code\s*>", r"`\1`", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*br\s*/?\s*>", "\n", converted, flags=re.IGNORECASE)
        # Drop any remaining HTML tags
        converted = re.sub(r"<[^>]+>", "", converted)
        # CommonMark → WA: **bold** → *bold*, __italic__ → _italic_
        converted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", converted, flags=re.DOTALL)
        converted = re.sub(r"__(.+?)__", r"_\1_", converted, flags=re.DOTALL)
        return converted

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        if not phone:
            return ""
        cleaned = (
            phone.strip()
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        if cleaned.startswith("08"):
            cleaned = "62" + cleaned[1:]
        return cleaned
