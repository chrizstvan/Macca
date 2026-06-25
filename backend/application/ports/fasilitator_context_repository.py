"""Read/write port for the ``fasilitator_context`` key/value store.

Holds free-form fasilitator configuration such as the project description
used to ground strategy consultations.
"""

from __future__ import annotations

from typing import Protocol


class FasilitatorContextRepository(Protocol):
    async def get(self, key: str) -> str | None:
        """Return the stored value for ``key``, or None if unset."""

    async def upsert(self, key: str, value: str) -> None:
        """Insert or update the value for ``key``."""
