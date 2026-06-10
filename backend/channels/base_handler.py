"""Abstract base class for all channel handlers."""

from abc import ABC, abstractmethod
from typing import Any


class BaseChannelHandler(ABC):
    """Defines the interface that every channel handler must implement.

    A channel handler is responsible for receiving raw incoming events from
    an external messaging platform, normalising them into a common format,
    dispatching them to the agent pipeline, and sending responses back.
    """

    @abstractmethod
    async def receive(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Parse a raw platform payload into a normalised message dict.

        Returns a dict with at minimum: ``user_id``, ``message``, ``channel``.
        """

    @abstractmethod
    async def send(self, recipient_id: str, message: str, **kwargs: Any) -> bool:
        """Deliver a text message to a recipient on this channel.

        Returns True on success, False on failure.
        """

    @abstractmethod
    async def send_photo(self, recipient_id: str, photo_url: str, caption: str = "") -> bool:
        """Deliver a photo message to a recipient on this channel."""
