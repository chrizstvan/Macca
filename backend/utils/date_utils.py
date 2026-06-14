"""Date/time parsing helpers used across agents and the ranking calculator.

Postgres/Supabase emits ISO-8601 timestamps with optional ``Z`` suffix.
All helpers here tolerate ``None``, missing timezones, and already-parsed
``date``/``datetime`` objects.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


def parse_iso_datetime(raw: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into a timezone-aware ``datetime``."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparseable datetime: %r", raw)
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_iso_date(raw: str | date | None) -> date | None:
    """Parse an ISO-8601 date string (or first 10 chars of a timestamp)."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        logger.warning("Unparseable date: %r", raw)
        return None


def format_hhmm(raw: str | datetime | None, fallback: str = "tadi") -> str:
    """Render an ISO timestamp (or datetime) as ``HH:MM``."""
    dt = parse_iso_datetime(raw)
    if dt is None:
        return fallback
    return dt.strftime("%H:%M")


def days_since(raw: str | datetime | None) -> int:
    """Whole days between ``raw`` and now (UTC). Negative results clamped to 0."""
    dt = parse_iso_datetime(raw)
    if dt is None:
        return 0
    delta = datetime.now(timezone.utc) - dt
    return max(delta.days, 0)
