"""Read-model (query-side) port for volunteer lookups.

Returns plain ``dict`` read DTOs — the shape agents already consume — rather
than the ``Volunteer`` domain entity. This is the CQRS *query* side: it
centralises every volunteer read behind one adapter (testable + a single
place to enforce row filtering) without forcing the presentation layer to
adopt the entity's value objects (``Phone``/``Kg``/``UUID``), which the
notification + channel paths still expect as plain dict values.

The entity-based ``VolunteerRepository`` remains the *command* side used by
use cases.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

VolunteerRow = dict[str, Any]


class VolunteerQueryRepository(Protocol):
    async def get_by_id(self, volunteer_id: UUID | str) -> VolunteerRow | None: ...

    async def get_by_telegram_id(
        self, telegram_id: int
    ) -> VolunteerRow | None: ...

    async def get_by_phone(self, phone: str) -> VolunteerRow | None:
        """Lookup by an already-normalised phone string."""

    async def list_active(self) -> list[VolunteerRow]: ...

    async def list_by_team(self, team: str) -> list[VolunteerRow]:
        """Active volunteers in ``team`` (coerced/compared case-insensitively)."""
        ...

    async def list_all(self) -> list[VolunteerRow]:
        """Every volunteer, active or not."""

    async def find_by_name(self, fragment: str) -> list[VolunteerRow]:
        """Case-insensitive ``ilike`` name match."""

    async def names_for(self, ids: list[str]) -> dict[str, str]:
        """Map of ``{volunteer_id: name}`` for the given ids."""
