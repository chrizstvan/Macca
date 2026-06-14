"""Channel-handler interfaces + the runtime factory.

Pass D split: the historical ``BaseChannelHandler`` lumped inbound and
outbound responsibilities into a single ABC. Concrete handlers paid for
both even when they only needed one (e.g. ``TelegramHandler``'s
``handle_incoming`` was a hard-coded ``return None``). The interface is
now decomposed into two cohesive protocols:

* :class:`InboundReceiver` — the bot's parsing/dispatch surface for an
  incoming webhook payload.
* :class:`OutboundSender` — the bot's outbound surface (DMs, media,
  buttons, alerts, identity check).

``BaseChannelHandler`` is preserved as the union of both so existing
imports (``WhatsAppHandler(BaseChannelHandler)``) keep working without
churn. New code that only needs to *send* (factory consumers, ad-hoc
notification helpers) can take an :class:`OutboundSender` parameter and
accept either handler — or the multi-channel fan-out wrapper.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any

logger = logging.getLogger(__name__)


class InboundReceiver(ABC):
    """A channel handler that consumes webhook payloads."""

    @abstractmethod
    async def handle_incoming(self, request_body: dict[str, Any]) -> None:
        """Entry point for an inbound webhook payload.

        Parse the platform payload, run any agent routing, and send replies
        back over the same channel. Errors should be caught and logged so a
        single bad event never blocks the webhook ack.
        """


class OutboundSender(ABC):
    """A channel handler that pushes messages out to recipients."""

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


class BaseChannelHandler(InboundReceiver, OutboundSender, ABC):
    """Union of both interfaces — used by handlers that genuinely do both.

    Kept for back-compat with existing concrete handlers and external
    imports. New code that only needs one half should depend on the
    narrower interface directly.
    """


class MultiChannelHandler(OutboundSender):
    """Fan-out wrapper that forwards outbound calls to several handlers.

    Inbound dispatch is *not* fanned out — the caller already knows which
    channel posted the webhook, so it should pick the right handler
    directly. That's why this class implements ``OutboundSender`` only:
    trying to receive on a multi-channel composite is a category error
    we'd rather catch at type-check time than at runtime.
    """

    def __init__(self, handlers: list[OutboundSender]) -> None:
        if not handlers:
            raise ValueError("MultiChannelHandler requires at least one handler")
        self.handlers = handlers

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


def get_active_handler() -> OutboundSender:
    """Return the outbound handler matching ``settings.active_channel``.

    Returns :class:`OutboundSender` because the factory's only stable
    contract is the ability to send messages — callers that need inbound
    dispatch should instantiate the concrete handler at the webhook entry
    point instead.

    Lazy imports avoid a circular dependency between this module and the
    concrete handlers (which import ``BaseChannelHandler`` from here).
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
