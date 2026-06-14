"""Read/write port for the volunteers aggregate."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.domain.entities.volunteer import Volunteer
from backend.domain.value_objects.phone import Phone


class VolunteerRepository(Protocol):
    async def get_by_id(self, volunteer_id: UUID) -> Volunteer | None: ...
    async def get_by_phone(self, phone: Phone) -> Volunteer | None: ...
    async def get_by_telegram_id(self, telegram_id: int) -> Volunteer | None: ...
    async def find_by_name(self, name_fragment: str) -> list[Volunteer]: ...
    async def list_active(self) -> list[Volunteer]: ...
    async def list_for_mission(self, mission_id: UUID) -> list[Volunteer]: ...
    async def save(self, volunteer: Volunteer) -> Volunteer:
        """Insert or update; returns the persisted entity (with id set)."""
