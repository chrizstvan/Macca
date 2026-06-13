"""Cloudinary uploads for volunteer report photos (with Telegram download support)."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from io import BytesIO

import cloudinary
import cloudinary.uploader
import httpx
from PIL import Image
from telegram.ext import Application

from backend.config import settings

WHATSAPP_GRAPH_BASE = "https://graph.facebook.com/v18.0"

logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
    secure=True,
)

MAX_IMAGE_BYTES = 1024 * 1024  # 1 MB
FOLDER = "bebas-plastik/reports"


class ImageHandler:
    """Compresses and uploads report photos to Cloudinary."""

    async def upload_photo(
        self, photo_bytes: bytes, volunteer_id: str, timestamp: str
    ) -> str | None:
        """Compress to <=1MB, upload to Cloudinary, and return the secure URL.

        Returns None (and logs the error) if the upload fails.
        """
        public_id = _sanitize(f"{volunteer_id}_{timestamp}")
        try:
            # Compression and the Cloudinary SDK are blocking — keep them off the event loop
            result = await asyncio.to_thread(self._compress_and_upload, photo_bytes, public_id)
            url: str = result["secure_url"]
            logger.info("Uploaded report photo %s/%s: %s", FOLDER, public_id, url)
            return url
        except Exception as exc:
            logger.error("Cloudinary upload failed for %s: %s", public_id, exc)
            return None

    async def upload_from_telegram(self, file_id: str, bot: Application) -> str | None:
        """Download a photo from Telegram by file_id and upload it to Cloudinary."""
        try:
            tg_bot = bot.bot if isinstance(bot, Application) else bot
            file = await tg_bot.get_file(file_id)
            photo_bytes = bytes(await file.download_as_bytearray())
        except Exception as exc:
            logger.error("Failed to download Telegram file %s: %s", file_id, exc)
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return await self.upload_photo(photo_bytes, file_id[:16], timestamp)

    async def upload_from_whatsapp(
        self, media_id: str, access_token: str, volunteer_id: str
    ) -> str | None:
        """Resolve a WhatsApp Cloud API media_id to bytes, then upload to Cloudinary.

        Two-step download required by the Graph API: GET /{media_id} returns a
        short-lived signed URL; that URL is then fetched with the same bearer
        token to retrieve the actual bytes.
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                meta_resp = await client.get(
                    f"{WHATSAPP_GRAPH_BASE}/{media_id}", headers=headers
                )
                meta_resp.raise_for_status()
                media_url = meta_resp.json().get("url")
                if not media_url:
                    logger.error("WhatsApp media %s: missing 'url' in metadata", media_id)
                    return None

                bin_resp = await client.get(media_url, headers=headers)
                bin_resp.raise_for_status()
                photo_bytes = bin_resp.content
        except httpx.HTTPError as exc:
            logger.error("Failed to download WhatsApp media %s: %s", media_id, exc)
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return await self.upload_photo(photo_bytes, volunteer_id, timestamp)

    @staticmethod
    def _compress_and_upload(photo_bytes: bytes, public_id: str) -> dict:
        return cloudinary.uploader.upload(
            BytesIO(_compress(photo_bytes)),
            folder=FOLDER,
            public_id=public_id,
            resource_type="image",
            quality="auto",
        )


def _compress(photo_bytes: bytes) -> bytes:
    """Re-encode as JPEG, lowering quality (then size) until under MAX_IMAGE_BYTES."""
    if len(photo_bytes) <= MAX_IMAGE_BYTES:
        return photo_bytes

    image = Image.open(BytesIO(photo_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")

    buffer = BytesIO()
    for quality in (85, 70, 55, 40):
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=quality, optimize=True)
        if buffer.tell() <= MAX_IMAGE_BYTES:
            return buffer.getvalue()

    while buffer.tell() > MAX_IMAGE_BYTES and min(image.size) > 200:
        image = image.resize((image.width // 2, image.height // 2))
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=40, optimize=True)
    return buffer.getvalue()


def _sanitize(public_id: str) -> str:
    """Strip characters Cloudinary rejects in public IDs (e.g. ':' from ISO timestamps)."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", public_id)
