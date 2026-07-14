"""Single live feature flag that disables ALL chat reporting.

``enable_reporting`` ( 'true' | 'false' ) gates BOTH volunteer WA reports and
fasilitator relay reports — one flag, no separate toggles. ``false`` makes the
report handlers reply with ``reporting_off_message`` instead of saving. Stored
in ``fasilitator_context`` (the live settings store the rest of the bot reads),
so flipping it on the dashboard takes effect with no restart.

Deliberately NOT applied to Google Form submissions: when WA reporting is off,
the form is the intended fallback ("isi form report"). Existing data, ranking,
and impact are untouched — turning the flag back on resumes reporting as-is.

Fail-open: a settings-read error returns "enabled" so a transient DB hiccup
never silently blocks legitimate reporting.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_OFF_MESSAGE = (
    "Silakan isi form report atau hubungi fasilitator untuk submit reportmu :)"
)


async def is_reporting_enabled() -> bool:
    """True unless ``enable_reporting`` is explicitly ``'false'``."""
    from backend.infrastructure.composition_root import (
        build_fasilitator_context_repository,
    )

    try:
        value = await build_fasilitator_context_repository().get("enable_reporting")
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning("enable_reporting read failed, defaulting on: %s", exc)
        return True
    return (value or "true").strip().lower() != "false"


async def reporting_off_message() -> str:
    """Fasilitator-configured off message, or a sensible default."""
    from backend.infrastructure.composition_root import (
        build_fasilitator_context_repository,
    )

    try:
        msg = await build_fasilitator_context_repository().get("reporting_off_message")
    except Exception as exc:  # noqa: BLE001
        logger.warning("reporting_off_message read failed: %s", exc)
        msg = None
    return msg or DEFAULT_OFF_MESSAGE
