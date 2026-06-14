"""Adapter wrapping the existing utils.PhotoVerifier behind the port.

Re-uses the same Claude vision verifier already deployed; just exposes
it via the application-layer Protocol. Replacing with a different
vision provider later means swapping this class only.
"""

from __future__ import annotations

from typing import Any

from backend.application.ports.photo_verifier import PhotoVerifier as PhotoVerifierPort
from backend.utils.photo_verifier import PhotoVerifier as LegacyPhotoVerifier


class ClaudePhotoVerifier(PhotoVerifierPort):
    def __init__(self) -> None:
        self._impl = LegacyPhotoVerifier()

    async def verify_or_skip(
        self,
        *,
        photo_url: str | None,
        reported_kg: float,
        volunteer_area: str,
        is_fasilitator_relay: bool,
        require_photo: bool = True,
    ) -> dict[str, Any]:
        return await self._impl.verify_or_skip(
            photo_url=photo_url,
            reported_kg=reported_kg,
            volunteer_area=volunteer_area,
            is_fasilitator_relay=is_fasilitator_relay,
            require_photo=require_photo,
        )
