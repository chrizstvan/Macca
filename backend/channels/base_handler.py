"""Abstract channel-handler interface + runtime factory.

Every concrete channel handler (Telegram, WhatsApp, ...) implements the
same surface so the rest of the application can stay channel-agnostic.
A ``get_active_handler()`` factory reads ``settings.active_channel`` and
returns the right instance — or a ``MultiChannelHandler`` when the
operator wants both wires active at once.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BaseChannelHandler(ABC):
    """Interface every channel handler must implement."""

    @abstractmethod
    async def handle_incoming(self, request_body: dict[str, Any]) -> None:
        """Entry point for an inbound webhook payload.

        Parse the platform payload, run any agent routing, and send replies
        back over the same channel. Errors should be caught and logged so a
        single bad event never blocks the webhook ack.
        """

    @abstractmethod
    async def send_message(self, to: str, text: str) -> bool:
        """Deliver a plain text message. Returns True on success."""

    @abstractmethod
    async def send_image(self, to: str, image_url: str, caption: str = "") -> bool:
        """Deliver an image (by URL) with optional caption."""

    @abstractmethod
    async def send_buttons(self, to: str, body_text: str, buttons: list[str]) -> bool:
        """Deliver an interactive message with up to 3 quick-reply buttons."""

    @abstractmethod
    async def send_read_receipt(self, to: str, message_id: str) -> None:
        """Mark an inbound message as read on the platform that supports it."""

    @abstractmethod
    async def download_media(self, media_id: str) -> bytes | None:
        """Fetch raw bytes for a platform-hosted media object."""

    @abstractmethod
    async def send_alert(self, text: str) -> None:
        """Send a high-priority message to the configured fasilitator."""

    @abstractmethod
    def is_fasilitator(self, sender_id: str) -> bool:
        """True if ``sender_id`` belongs to the fasilitator on this channel."""


class MultiChannelHandler(BaseChannelHandler):
    """Fan-out wrapper that forwards outbound calls to several handlers.

    Inbound (``handle_incoming``) is *not* fanned out — the caller already
    knows which channel posted the webhook, so it should pick the right
    handler directly. The wrapper raises if ``handle_incoming`` is called
    here so misuse fails loudly.
    """

    def __init__(self, handlers: list[BaseChannelHandler]) -> None:
        if not handlers:
            raise ValueError("MultiChannelHandler requires at least one handler")
        self.handlers = handlers

    async def handle_incoming(self, request_body: dict[str, Any]) -> None:
        raise NotImplementedError(
            "Route inbound webhooks through a specific handler, not MultiChannelHandler"
        )

    async def send_message(self, to: str, text: str) -> bool:
        results = [await h.send_message(to, text) for h in self.handlers]
        return any(results)

    async def send_image(self, to: str, image_url: str, caption: str = "") -> bool:
        results = [await h.send_image(to, image_url, caption) for h in self.handlers]
        return any(results)

    async def send_buttons(self, to: str, body_text: str, buttons: list[str]) -> bool:
        results = [await h.send_buttons(to, body_text, buttons) for h in self.handlers]
        return any(results)

    async def send_read_receipt(self, to: str, message_id: str) -> None:
        for h in self.handlers:
            await h.send_read_receipt(to, message_id)

    async def download_media(self, media_id: str) -> bytes | None:
        for h in self.handlers:
            data = await h.download_media(media_id)
            if data is not None:
                return data
        return None

    async def send_alert(self, text: str) -> None:
        for h in self.handlers:
            await h.send_alert(text)

    def is_fasilitator(self, sender_id: str) -> bool:
        return any(h.is_fasilitator(sender_id) for h in self.handlers)


def get_active_handler() -> BaseChannelHandler:
    """Return the channel handler matching ``settings.active_channel``.

    Lazy imports avoid a circular dependency between this module and the
    concrete handlers (which import ``BaseChannelHandler``).
    """
    from backend.config import settings

    channel = (settings.active_channel or "telegram").lower()

    if channel == "whatsapp":
        from .whatsapp_handler import WhatsAppHandler

        return WhatsAppHandler()

    if channel == "both":
        from .telegram_channel_handler import TelegramHandler
        from .whatsapp_handler import WhatsAppHandler

        return MultiChannelHandler([TelegramHandler(), WhatsAppHandler()])

    from .telegram_channel_handler import TelegramHandler

    return TelegramHandler()
