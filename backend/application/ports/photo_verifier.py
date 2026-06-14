"""Photo verification port — abstracts the vision LLM behind a verdict."""

from __future__ import annotations

from typing import Any, Protocol


class PhotoVerifier(Protocol):
    async def verify_or_skip(
        self,
        *,
        photo_url: str | None,
        reported_kg: float,
        volunteer_area: str,
        is_fasilitator_relay: bool,
        require_photo: bool = True,
    ) -> dict[str, Any]:
        """Return a verdict dict with at least ``verdict`` and ``should_flag``.

        See ``backend.utils.photo_verifier`` for the canonical key set.
        """
