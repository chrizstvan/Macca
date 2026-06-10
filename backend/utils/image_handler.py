"""Cloudinary-backed image upload and URL generation utilities."""

import logging
from io import BytesIO
from typing import Any

import cloudinary
import cloudinary.uploader

from backend.config import config

logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=config.CLOUDINARY_CLOUD_NAME,
    api_key=config.CLOUDINARY_API_KEY,
    api_secret=config.CLOUDINARY_API_SECRET,
    secure=True,
)


class ImageHandler:
    """Handles uploading volunteer progress photos to Cloudinary.

    Images are stored under a per-mission folder and tagged for easy
    retrieval when generating impact reports.
    """

    FOLDER_PREFIX = "macca"

    def upload_from_bytes(
        self,
        data: bytes,
        mission_id: str,
        volunteer_id: str,
        tags: list[str] | None = None,
    ) -> str | None:
        """Upload raw image bytes to Cloudinary and return the secure URL."""
        try:
            result = cloudinary.uploader.upload(
                BytesIO(data),
                folder=f"{self.FOLDER_PREFIX}/{mission_id}",
                public_id=f"{volunteer_id}_{_timestamp()}",
                tags=tags or ["macca", mission_id],
                resource_type="image",
            )
            url: str = result.get("secure_url", "")
            logger.info("Uploaded image for mission %s: %s", mission_id, url)
            return url
        except Exception as exc:
            logger.error("Cloudinary upload failed: %s", exc)
            return None

    def upload_from_url(self, url: str, mission_id: str, volunteer_id: str) -> str | None:
        """Re-upload an image from an existing URL (e.g., Telegram CDN) to Cloudinary."""
        try:
            result = cloudinary.uploader.upload(
                url,
                folder=f"{self.FOLDER_PREFIX}/{mission_id}",
                public_id=f"{volunteer_id}_{_timestamp()}",
                tags=["macca", mission_id],
            )
            return result.get("secure_url")
        except Exception as exc:
            logger.error("Cloudinary re-upload from URL failed: %s", exc)
            return None

    def list_mission_images(self, mission_id: str) -> list[dict[str, Any]]:
        """Return all images stored for a given mission."""
        try:
            result = cloudinary.api.resources_by_tag(mission_id, resource_type="image")
            return result.get("resources", [])
        except Exception as exc:
            logger.error("Failed to list Cloudinary images for mission %s: %s", mission_id, exc)
            return []


def _timestamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
