"""Schedule-intent parser for fasilitator reminder approvals (Bagian B).

Turns a fasilitator's free-form approval message into a concrete send time.
Applies ONLY to reminders, never to volunteer interactions (Bagian C).

Four modes are recognised, in priority order:

* ``immediate``     — "kirim sekarang", "langsung", "now", "segera".
* ``relative``      — "24 jam lagi", "3 jam lagi", "2 hari lagi".
* ``absolute``      — natural Indonesian datetime ("6 Juli jam 7 malam",
                      "besok jam 8 pagi") resolved via Claude Haiku.
* ``default_delay`` — plain "kirim": uses the ``reminder_delay_hours``
                      setting (default 8h).

Stateless helper mirroring :class:`backend.utils.volunteer_resolver`: the
LLM caller is injected (a bound ``BaseAgent.call_claude``) and only used by
the absolute-datetime path. The reminder-delay setting is read through the
``FasilitatorContextRepository`` port (lazy-built to avoid the
composition-root import cycle).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Western Indonesian Time — same literal the scheduler pins its crons to.
WIB = ZoneInfo("Asia/Jakarta")

_DEFAULT_DELAY_HOURS = 8
_DELAY_SETTING_KEY = "reminder_delay_hours"

_IMMEDIATE_WORDS = ("sekarang", "langsung", "now", "segera")

_RELATIVE_PATTERN = re.compile(r"(\d+)\s*(menit|jam|hari)\s*lagi")
_RELATIVE_DELTA = {
    "menit": lambda n: timedelta(minutes=n),
    "jam": lambda n: timedelta(hours=n),
    "hari": lambda n: timedelta(days=n),
}

# Words that hint at an absolute date/time worth sending to the LLM parser.
_ABSOLUTE_HINTS = (
    "tanggal", "jam", "besok", "lusa",
    "senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu",
    "pagi", "siang", "sore", "malam",
    "januari", "februari", "maret", "april", "mei", "juni",
    "juli", "agustus", "september", "oktober", "november", "desember",
)

_DATETIME_PROMPT_TEMPLATE = (
    "Sekarang: {now} WIB ({weekday}).\n"
    'Ubah ke datetime: "{text}"\n'
    "Jawab HANYA format ISO: YYYY-MM-DD HH:MM\n"
    'Kalau tidak ada info waktu jelas, jawab "NONE".\n'
    '"jam 7 malam"=19:00, "jam 8 pagi"=08:00, "jam 2 siang"=14:00, '
    '"jam 5 sore"=17:00'
)


class ScheduleParser:
    """Approval-message → send-time resolver.

    ``llm_caller`` is the bound ``call_claude`` of any ``BaseAgent`` subclass;
    omit it to disable the absolute-datetime path (it then falls through to
    the default-delay mode).
    """

    def __init__(self, *, llm_caller: Any = None) -> None:
        self._llm = llm_caller

    # ------------------------------------------------------------------ #
    # Main entry                                                         #
    # ------------------------------------------------------------------ #

    async def parse_send_time(self, message: str) -> dict:
        """Decide when a reminder is sent from the approval message.

        Returns ``{"mode": str, "send_at": datetime, "label": str}`` with a
        timezone-aware ``send_at`` in WIB.
        """
        msg = (message or "").lower().strip()
        now = datetime.now(WIB)

        # MODE 4 — Immediate.
        if any(k in msg for k in _IMMEDIATE_WORDS):
            return {"mode": "immediate", "send_at": now, "label": "sekarang"}

        # MODE 2 — Relative ("24 jam lagi", "2 hari lagi").
        rel = _RELATIVE_PATTERN.search(msg)
        if rel:
            n = int(rel.group(1))
            unit = rel.group(2)
            send_at = now + _RELATIVE_DELTA[unit](n)
            return {
                "mode": "relative",
                "send_at": send_at,
                "label": f"{n} {unit} lagi ({send_at.strftime('%H:%M, %d %b')})",
            }

        # MODE 3 — Absolute datetime (LLM-parsed Indonesian).
        if any(k in msg for k in _ABSOLUTE_HINTS):
            parsed_dt = await self.parse_indonesian_datetime(msg, reference=now)
            if parsed_dt:
                return {
                    "mode": "absolute",
                    "send_at": parsed_dt,
                    "label": parsed_dt.strftime("%H:%M, %d %B %Y"),
                }

        # MODE 1 — Default delay (plain "kirim").
        delay_hours = await self._reminder_delay_hours()
        send_at = now + timedelta(hours=delay_hours)
        return {
            "mode": "default_delay",
            "send_at": send_at,
            "label": f"{delay_hours} jam lagi ({send_at.strftime('%H:%M, %d %b')})",
        }

    # ------------------------------------------------------------------ #
    # Absolute datetime via Claude                                       #
    # ------------------------------------------------------------------ #

    async def parse_indonesian_datetime(
        self, text: str, reference: datetime
    ) -> datetime | None:
        """Parse natural Indonesian date/time using Claude Haiku.

        ``"6 Juli jam 7 malam"`` → ``2026-07-06 19:00``;
        ``"besok jam 8 pagi"`` → tomorrow 08:00. Returns a WIB-aware
        ``datetime`` or None when no clear time is present / on parse failure.
        """
        if self._llm is None:
            return None

        prompt = _DATETIME_PROMPT_TEMPLATE.format(
            now=reference.strftime("%Y-%m-%d %H:%M"),
            weekday=reference.strftime("%A"),
            text=text,
        )
        try:
            result = await self._llm(
                prompt,
                [{"role": "user", "content": text}],
                max_tokens=24,
            )
        except Exception as exc:  # noqa: BLE001 — never crash the approval flow
            logger.warning("indonesian datetime parse failed: %s", exc)
            return None

        result = (result or "").strip()
        if not result or "NONE" in result:
            return None
        try:
            return datetime.strptime(result, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
        except ValueError:
            logger.warning("LLM returned non-ISO datetime: %r", result)
            return None

    # ------------------------------------------------------------------ #
    # Settings                                                           #
    # ------------------------------------------------------------------ #

    async def _reminder_delay_hours(self) -> int:
        """Read ``reminder_delay_hours`` from fasilitator context (default 8)."""
        # Lazy import: composition_root → notifier → channels → agents cycle.
        from backend.infrastructure.composition_root import (
            build_fasilitator_context_repository,
        )

        try:
            raw = await build_fasilitator_context_repository().get(_DELAY_SETTING_KEY)
            return int(raw) if raw else _DEFAULT_DELAY_HOURS
        except (ValueError, TypeError):
            return _DEFAULT_DELAY_HOURS
        except Exception as exc:  # noqa: BLE001 — setting read must not crash
            logger.warning("reminder_delay_hours read failed: %s", exc)
            return _DEFAULT_DELAY_HOURS
