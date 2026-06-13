"""Application settings loaded from the .env file via python-dotenv.

Exports a module-level ``settings`` singleton. Import it anywhere with::

    from backend.config import settings
"""

import os
from typing import ClassVar

from dotenv import load_dotenv


class SettingsError(Exception):
    """Raised when required environment configuration is missing or invalid."""


class Settings:
    """Typed application settings with singleton semantics.

    Environment variables are read exactly once, on first instantiation.
    Every subsequent ``Settings()`` call returns the same instance.
    """

    _instance: ClassVar["Settings | None"] = None

    anthropic_api_key: str
    telegram_bot_token: str
    supabase_url: str
    supabase_key: str
    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_api_secret: str
    webhook_url: str
    fasilitator_telegram_id: int = 0

    # WhatsApp Cloud API
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = ""

    # Fasilitator identity (works for both Telegram and WhatsApp)
    fasilitator_phone: str = ""

    # Test mode
    test_mode_enabled: bool = True

    # Active channel — which is primary right now
    active_channel: str = "telegram"

    claude_model: str = "claude-sonnet-4-6"
    max_tokens: int = 1000

    def __new__(cls) -> "Settings":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._load()
            cls._instance = instance
        return cls._instance

    def _load(self) -> None:
        """Read and validate all required environment variables."""
        load_dotenv()

        self.anthropic_api_key = self._require("ANTHROPIC_API_KEY")
        self.telegram_bot_token = self._require("TELEGRAM_BOT_TOKEN")
        self.supabase_url = self._require("SUPABASE_URL")
        self.supabase_key = self._require("SUPABASE_KEY")
        self.cloudinary_cloud_name = self._require("CLOUDINARY_CLOUD_NAME")
        self.cloudinary_api_key = self._require("CLOUDINARY_API_KEY")
        self.cloudinary_api_secret = self._require("CLOUDINARY_API_SECRET")
        self.webhook_url = self._require("WEBHOOK_URL")

        raw_fasilitator_id = os.getenv("FASILITATOR_TELEGRAM_ID", "").strip()
        if raw_fasilitator_id:
            try:
                self.fasilitator_telegram_id = int(raw_fasilitator_id)
            except ValueError:
                raise SettingsError(
                    f"FASILITATOR_TELEGRAM_ID must be an integer Telegram chat ID, "
                    f"got: {raw_fasilitator_id!r}"
                ) from None
        else:
            self.fasilitator_telegram_id = 0

        # WhatsApp Cloud API (optional until channel enabled)
        self.whatsapp_phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self.whatsapp_business_account_id = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
        self.whatsapp_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        self.whatsapp_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

        # Fasilitator phone (WhatsApp identity)
        self.fasilitator_phone = os.getenv("FASILITATOR_PHONE", "")

        # Test mode toggle
        self.test_mode_enabled = os.getenv("TEST_MODE_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # Active channel
        active_channel = os.getenv("ACTIVE_CHANNEL", "telegram").lower().strip()
        if active_channel not in {"telegram", "whatsapp", "both"}:
            raise SettingsError(
                f"ACTIVE_CHANNEL must be one of 'telegram', 'whatsapp', 'both', "
                f"got: {active_channel!r}"
            )
        self.active_channel = active_channel

    @staticmethod
    def _require(name: str) -> str:
        """Return the value of an environment variable or raise a clear error."""
        value = os.getenv(name)
        if not value:
            raise SettingsError(
                f"Missing required environment variable: {name}. "
                f"Add it to your .env file (see .env.example for the full list)."
            )
        return value


settings = Settings()
