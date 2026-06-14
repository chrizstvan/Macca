"""Real-time UTC clock adapter."""

from datetime import date, datetime, timezone

from backend.application.ports.clock import Clock


class UtcClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def today(self) -> date:
        return self.now().date()
