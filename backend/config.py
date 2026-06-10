"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
    TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
    SUPABASE_URL: str = os.environ["SUPABASE_URL"]
    SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]
    CLOUDINARY_CLOUD_NAME: str = os.environ["CLOUDINARY_CLOUD_NAME"]
    CLOUDINARY_API_KEY: str = os.environ["CLOUDINARY_API_KEY"]
    CLOUDINARY_API_SECRET: str = os.environ["CLOUDINARY_API_SECRET"]
    WEBHOOK_URL: str = os.environ["WEBHOOK_URL"]
    FASILITATOR_TELEGRAM_ID: str = os.environ["FASILITATOR_TELEGRAM_ID"]

    CLAUDE_MODEL: str = "claude-sonnet-4-6"
    MAX_TOKENS: int = 4096


config = Config()
