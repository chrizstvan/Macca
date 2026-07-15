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
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = ""
    # Message-template defaults (for cold / >24h sends — see send_template)
    whatsapp_template_lang: str = "id"
    whatsapp_welcome_template: str = "onboard_volunteer"

    # Fasilitator identity (works for both Telegram and WhatsApp)
    fasilitator_phone: str = ""

    # Test mode — controls whether /test_as is allowed.
    test_mode_enabled: bool = True

    # Active channel — primary outbound channel; fallback is the other one.
    active_channel: str = "telegram"

    # Streamlit dashboard admin bearer token. Empty → admin endpoints open
    # in development only; in production an empty token makes them fail closed.
    admin_token: str = ""

    # Deployment environment. ``production`` makes admin auth fail closed and
    # turns missing webhook secrets into loud errors.
    environment: str = "development"

    # Webhook authenticity secrets — enforced whenever set.
    whatsapp_app_secret: str = ""       # Meta app secret → X-Hub-Signature-256 HMAC
    telegram_webhook_secret: str = ""   # X-Telegram-Bot-Api-Secret-Token header
    google_form_secret: str = ""        # shared secret from the Apps Script relay

    # Browser origins allowed to call the API (the dashboard). Webhooks are
    # server-to-server and don't need CORS. Comma-separated env override.
    cors_allow_origins: list[str] = ["http://localhost:8501"]

    # Whether a volunteer can query data about another volunteer (limited
    # fields). Default off — only the fasilitator sees peer data.
    allow_peer_query: bool = False

    # Claude model defaults (override via env so we can swap models without
    # touching code).
    claude_default_model: str = "claude-haiku-4-5-20251001"
    claude_complex_model: str = "claude-sonnet-4-6"
    default_max_tokens: int = 500

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
        self.whatsapp_access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        self.whatsapp_verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
        self.whatsapp_template_lang = os.getenv("WHATSAPP_TEMPLATE_LANG", "id")
        self.whatsapp_welcome_template = os.getenv(
            "WHATSAPP_WELCOME_TEMPLATE", "onboard_volunteer"
        )

        # Fasilitator phone (WhatsApp identity)
        self.fasilitator_phone = os.getenv("FASILITATOR_PHONE", "")

        # Test mode toggle
        self.test_mode_enabled = os.getenv("TEST_MODE_ENABLED", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # Dashboard admin token (optional)
        self.admin_token = os.getenv("ADMIN_TOKEN", "")

        # Deployment environment + webhook authenticity secrets
        self.environment = os.getenv("ENVIRONMENT", "development").lower().strip()
        self.whatsapp_app_secret = os.getenv("WHATSAPP_APP_SECRET", "")
        self.telegram_webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
        self.google_form_secret = os.getenv("GOOGLE_FORM_SECRET", "")
        self.cors_allow_origins = [
            o.strip()
            for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8501").split(",")
            if o.strip()
        ]

        # Active channel
        active_channel = os.getenv("ACTIVE_CHANNEL", "telegram").lower().strip()
        if active_channel not in {"telegram", "whatsapp", "both"}:
            raise SettingsError(
                f"ACTIVE_CHANNEL must be one of 'telegram', 'whatsapp', 'both', "
                f"got: {active_channel!r}"
            )
        self.active_channel = active_channel

        # Peer-query permission toggle
        self.allow_peer_query = os.getenv("ALLOW_PEER_QUERY", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # Claude model + max-tokens defaults
        self.claude_default_model = os.getenv(
            "CLAUDE_DEFAULT_MODEL", "claude-haiku-4-5-20251001"
        )
        self.claude_complex_model = os.getenv(
            "CLAUDE_COMPLEX_MODEL", "claude-sonnet-4-6"
        )
        try:
            self.default_max_tokens = int(os.getenv("DEFAULT_MAX_TOKENS", "1000"))
        except ValueError as exc:
            raise SettingsError(
                f"DEFAULT_MAX_TOKENS must be an integer, got: "
                f"{os.getenv('DEFAULT_MAX_TOKENS')!r}"
            ) from exc

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
