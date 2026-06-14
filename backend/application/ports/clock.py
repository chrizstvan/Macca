"""Time source — injecting this makes use cases trivially testable."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol


class Clock(Protocol):
    """Read-only access to "now" with timezone."""

    def now(self) -> datetime: ...
    def today(self) -> date: ...
