"""Telegram channel handler using python-telegram-bot v20."""

import logging
from typing import Any

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from backend.config import settings
from .base_handler import BaseChannelHandler

logger = logging.getLogger(__name__)


class TelegramHandler(BaseChannelHandler):
    """Handles all Telegram bot interactions for Macca.

    Wraps python-telegram-bot v20's Application to register command and
    message handlers, set the webhook, and provide send/receive helpers
    used by the agent pipeline.
    """

    def __init__(self) -> None:
        self._bot = Bot(token=settings.telegram_bot_token)
        self._app: Application | None = None

    def build_application(self) -> Application:
        """Build and configure the telegram Application with all handlers."""
        self._app = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("help", self._handle_help))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        return self._app

    async def receive(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Parse a Telegram webhook payload into a normalised message dict."""
        update = Update.de_json(payload, self._bot)
        message = update.message or update.edited_message
        if not message:
            return {}

        return {
            "user_id": str(message.from_user.id),
            "username": message.from_user.username or "",
            "message": message.text or "",
            "photo": message.photo[-1].file_id if message.photo else None,
            "channel": "telegram",
            "chat_id": str(message.chat_id),
            "update_id": update.update_id,
        }

    async def send(self, recipient_id: str, message: str, **kwargs: Any) -> bool:
        """Send a text message to a Telegram chat."""
        try:
            await self._bot.send_message(
                chat_id=recipient_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                **kwargs,
            )
            return True
        except Exception as exc:
            logger.error("Failed to send Telegram message to %s: %s", recipient_id, exc)
            return False

    async def send_photo(self, recipient_id: str, photo_url: str, caption: str = "") -> bool:
        """Send a photo with optional caption to a Telegram chat."""
        try:
            await self._bot.send_photo(
                chat_id=recipient_id,
                photo=photo_url,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
            return True
        except Exception as exc:
            logger.error("Failed to send Telegram photo to %s: %s", recipient_id, exc)
            return False

    async def set_webhook(self) -> bool:
        """Register the webhook URL with Telegram."""
        try:
            await self._bot.set_webhook(url=settings.webhook_url)
            logger.info("Webhook set to %s", settings.webhook_url)
            return True
        except Exception as exc:
            logger.error("Failed to set webhook: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Internal handlers (used by Application, not the agent pipeline)     #
    # ------------------------------------------------------------------ #

    async def _handle_start(self, update: Update, _context: Any) -> None:
        await update.message.reply_text(
            "Welcome to *Macca* — your volunteer coordination assistant! "
            "Send me a message and I'll connect you with the right resource.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _handle_help(self, update: Update, _context: Any) -> None:
        help_text = (
            "*Macca Bot Commands*\n"
            "/start — Welcome message\n"
            "/help — Show this help\n\n"
            "Just type your question or update and I'll route it to the right agent."
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def _handle_message(self, update: Update, _context: Any) -> None:
        """Placeholder — real routing happens via the webhook endpoint."""
        logger.debug("Message received from %s", update.message.from_user.id)

    async def _handle_photo(self, update: Update, _context: Any) -> None:
        """Placeholder — photo handling routed via the webhook endpoint."""
        logger.debug("Photo received from %s", update.message.from_user.id)
