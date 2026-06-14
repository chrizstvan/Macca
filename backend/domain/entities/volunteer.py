"""Volunteer entity — identity by id, mutable state through methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from backend.domain.value_objects.kg import Kg
from backend.domain.value_objects.phone import Phone


@dataclass
class Volunteer:
    id: UUID
    name: str
    area: str
    quota_kg: Kg
    phone: Phone | None = None
    telegram_id: int | None = None
    is_active: bool = True
    team: list[str] = field(default_factory=list)

    # Per-day mission_briefing cap state
    mission_query_count: int = 0
    mission_query_reset_at: date | None = None

    # WhatsApp-onboarding state
    whatsapp_connected: bool = False
    first_contact_at: datetime | None = None
    last_contact_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("volunteer requires a name")
        if self.phone is None and self.telegram_id is None:
            raise ValueError("volunteer needs at least one channel identity")

    def is_fasilitator_for(
        self,
        *,
        fasilitator_phone: Phone | None,
        fasilitator_telegram_id: int | None,
    ) -> bool:
        if (
            self.phone is not None
            and fasilitator_phone is not None
            and self.phone == fasilitator_phone
        ):
            return True
        if (
            self.telegram_id is not None
            and fasilitator_telegram_id is not None
            and self.telegram_id == fasilitator_telegram_id
        ):
            return True
        return False

    def reset_daily_quota_if_needed(self, today: date) -> bool:
        """Returns True if the counter was actually reset this call."""
        if self.mission_query_reset_at is None or self.mission_query_reset_at < today:
            self.mission_query_count = 0
            self.mission_query_reset_at = today
            return True
        return False

    def mark_contacted(self, now: datetime) -> bool:
        """Record an inbound contact. Returns True iff this is the first contact.

        First contact flips ``whatsapp_connected`` to True and stamps
        ``first_contact_at``. Either way ``last_contact_at`` is updated.
        """
        is_first = not self.whatsapp_connected
        if is_first:
            self.whatsapp_connected = True
            self.first_contact_at = now
        self.last_contact_at = now
        return is_first

    def consume_mission_query(self, *, daily_limit: int, today: date) -> bool:
        """Try to spend one slot of the mission_briefing daily quota.

        Returns False when the volunteer has hit the cap; caller should
        reply with the canned over-limit message instead of calling the
        LLM.
        """
        self.reset_daily_quota_if_needed(today)
        if self.mission_query_count >= daily_limit:
            return False
        self.mission_query_count += 1
        return True
