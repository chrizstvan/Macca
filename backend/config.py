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
    fasilitator_telegram_id: int

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

        raw_fasilitator_id = self._require("FASILITATOR_TELEGRAM_ID")
        try:
            self.fasilitator_telegram_id = int(raw_fasilitator_id)
        except ValueError:
            raise SettingsError(
                f"FASILITATOR_TELEGRAM_ID must be an integer Telegram chat ID, "
                f"got: {raw_fasilitator_id!r}"
            ) from None

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
