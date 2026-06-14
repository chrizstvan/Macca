"""In-memory pending-report state shared between turns of a chat report.

Two channels can park state here:

* Telegram users — keyed by ``telegram_id`` (int).
* WhatsApp users — keyed by ``sender_phone`` (str).

Each entry expires 10 minutes after creation; ``cleanup_expired()`` runs
periodically from the scheduler to evict stale rows. The module-level
``store`` dict is the canonical state — callers may import it directly
when they need to inspect or clear it (used by the test suite).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

PendingKey = int | str

PENDING_TTL = timedelta(minutes=10)

#: Shared mutable state — DO NOT replace this binding (tests + agents
#: hold references to this exact dict). ``.clear()`` is fine.
store: dict[PendingKey, dict] = {}


def pending_key(context: dict | None) -> PendingKey | None:
    """Resolve a channel-stable key from a request context."""
    if not context:
        return None
    telegram_id = context.get("telegram_id")
    if telegram_id:
        return telegram_id
    sender_phone = context.get("sender_phone")
    if sender_phone:
        return str(sender_phone)
    return None


def set_pending(
    key: PendingKey | None,
    step: str,
    data: dict,
    existing_report_id: str | None = None,
) -> None:
    """Park ``(step, data)`` under ``key``. No-op for ``None`` keys."""
    if key is None:
        return
    store[key] = {
        "step": step,  # waiting_kg | waiting_location | waiting_confirmation
        "data": data,
        "existing_report_id": existing_report_id,
        "expires_at": datetime.now(timezone.utc) + PENDING_TTL,
    }


def has_pending(key: PendingKey | None) -> bool:
    """True if there is an unexpired entry for ``key``."""
    if key is None:
        return False
    entry = store.get(key)
    if entry is None:
        return False
    if entry["expires_at"] < datetime.now(timezone.utc):
        del store[key]
        return False
    return True


def has_pending_for_context(context: dict | None) -> bool:
    """Channel-aware ``has_pending`` used by the router."""
    return has_pending(pending_key(context))


async def cleanup_expired() -> None:
    """Scheduler job: drop expired entries (runs every 5 minutes)."""
    now = datetime.now(timezone.utc)
    expired = [k for k, entry in store.items() if entry["expires_at"] < now]
    for key in expired:
        del store[key]
    if expired:
        logger.info("Cleaned up %d expired pending report state(s)", len(expired))
