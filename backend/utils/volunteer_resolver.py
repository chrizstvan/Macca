"""Volunteer identity resolver — phone, @username, partial name → volunteer row.

Used by:

* ``FasilitatorHubAgent`` to translate '@rizki' / 'progress sari' into the
  underlying volunteer record.
* ``RouterAgent`` to detect cross-volunteer queries before classification
  so peer-query permission gating fires.
* Other agents that need name lookups can share the same logic instead of
  rolling their own ``ilike`` queries.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.config import settings
from backend.utils.phone_utils import normalize_phone

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


_USERNAME_PATTERN = re.compile(r"@([A-Za-z][\w'.-]*)", re.UNICODE)

# Keyword-triggered name mentions:
#   - "tugas X" / "progress X" / "info X" / etc → name follows keyword
#   - "X sudah lapor" / "X udah lapor" / "X belum lapor" → name precedes keyword
_KEYWORD_NAME_PATTERN = re.compile(
    r"\b(?:tugas|progress|info|laporan|status|kabar|update|detail|volunteer)"
    r"(?:\s+volunteer)?\s+"
    r"@?([A-Za-z][\w'.-]*(?:\s+[A-Za-z][\w'.-]*)?)|"
    r"\b@?([A-Za-z][\w'.-]+)\s+(?:sudah|udah|belum|lagi)\s+(?:lapor|kerja|aktif|on|setor)",
    re.IGNORECASE,
)

# Pronouns / self-referent / generic-determiner words that must never be
# treated as another volunteer's name.
_SELF_PRONOUNS: frozenset[str] = frozenset(
    {
        # First / second / third person pronouns
        "saya", "aku", "gue", "gw", "kami", "kita", "kamu", "anda", "lo", "lu",
        "dia", "mereka",
        # Determiners / generic noun-equivalents that aren't names
        "yang", "semua", "siapa", "ini", "itu", "mana", "volunteer", "warga",
        "tim", "kak", "pak", "bu", "bapak", "ibu",
        # Report-flow vocabulary — must never be misread as a person's name
        "foto", "fotonya", "kg", "kilo", "berat", "hari", "ini",
        "harian", "mingguan", "bulanan", "tahunan",
        "plastik", "sampah", "lokasi", "area",
    }
)

_LLM_EXTRACT_PROMPT = (
    "Identifikasi semua NAMA ORANG yang sedang ditanyakan dalam pesan ini "
    "(misal 'apa tugas Rizki sama Sari hari ini?'). Jangan masukkan kata "
    "umum, kata kerja, atau nama lokasi. Balas hanya JSON list of strings, "
    "contoh: [\"Rizki\", \"Sari\"]. Jika tidak ada nama orang yang "
    "ditanyakan, balas []."
)


# --------------------------------------------------------------------------- #
# Resolver                                                                     #
# --------------------------------------------------------------------------- #


class VolunteerResolver:
    """Phone / username / name → volunteer-row resolver.

    Stateless helper; instantiate per call or reuse — both are fine. The
    ``llm_caller`` argument is the bound ``call_claude`` method of any
    ``BaseAgent`` subclass; it's only used by
    :meth:`extract_volunteer_mentions` to disambiguate free-form name
    mentions and can be omitted when the caller only needs the cheap
    pattern-based path.
    """

    def __init__(self, db_client: Any, *, llm_caller: Any = None) -> None:
        self._db = db_client
        self._llm = llm_caller

    # ------------------------------------------------------------------ #
    # Single identifier                                                  #
    # ------------------------------------------------------------------ #

    async def resolve_volunteer(
        self, identifier: str
    ) -> dict | list[dict] | None:
        """Return one volunteer dict, list of matches, or None.

        Resolution order: normalised phone → exact lower-case name →
        case-insensitive partial name match.
        """
        if not identifier:
            return None
        cleaned = identifier.strip().lstrip("@").lower()
        if not cleaned:
            return None

        # 1. Phone match
        canonical_phone = normalize_phone(cleaned)
        if canonical_phone and canonical_phone.isdigit() and len(canonical_phone) >= 8:
            rows = (
                self._db.table("volunteers")
                .select("id, name, area, quota_kg, phone, telegram_id, team")
                .eq("phone", canonical_phone)
                .limit(1)
                .execute()
                .data
                or []
            )
            if rows:
                return rows[0]

        # 2. Exact name match
        rows = (
            self._db.table("volunteers")
            .select("id, name, area, quota_kg, phone, telegram_id, team")
            .ilike("name", cleaned)
            .execute()
            .data
            or []
        )
        if len(rows) == 1:
            return rows[0]
        if rows:
            return rows  # multiple exact-ish — let caller disambiguate

        # 3. Partial name match
        rows = (
            self._db.table("volunteers")
            .select("id, name, area, quota_kg, phone, telegram_id, team")
            .ilike("name", f"%{cleaned}%")
            .execute()
            .data
            or []
        )
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]
        return rows

    # ------------------------------------------------------------------ #
    # Free-form extraction                                                #
    # ------------------------------------------------------------------ #

    async def extract_volunteer_mentions(
        self, message: str
    ) -> list[dict]:
        """Find every volunteer the message refers to.

        Combines:
        * ``@username`` regex,
        * keyword-triggered name patterns (``tugas X``, ``progress X`` …),
        * a Haiku fallback when ``llm_caller`` is provided — useful for
          mentions that don't sit next to a recognised keyword.

        Returns a deduplicated list (by ``id``).
        """
        if not message:
            return []

        candidates: list[str] = []
        for m in _USERNAME_PATTERN.finditer(message):
            candidates.append(m.group(1))
        for m in _KEYWORD_NAME_PATTERN.finditer(message):
            name = (m.group(1) or m.group(2) or "").strip()
            if not name:
                continue
            first_token = name.lower().split()[0]
            if first_token in _SELF_PRONOUNS:
                continue
            candidates.append(name)

        if not candidates and self._llm is not None:
            try:
                raw = await self._llm(
                    _LLM_EXTRACT_PROMPT,
                    [{"role": "user", "content": message}],
                    max_tokens=80,
                )
                match = re.search(r"\[.*\]", raw or "", re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    candidates.extend(str(x).strip() for x in parsed if str(x).strip())
            except Exception as exc:
                logger.warning("LLM name extract failed: %s", exc)

        resolved: dict[str, dict] = {}
        for cand in candidates:
            hit = await self.resolve_volunteer(cand)
            if hit is None:
                continue
            if isinstance(hit, list):
                # Skip ambiguous matches — caller will need to disambiguate.
                continue
            resolved[hit["id"]] = hit
        return list(resolved.values())


# --------------------------------------------------------------------------- #
# Permission policy                                                            #
# --------------------------------------------------------------------------- #


def can_query_volunteer(
    *,
    requester_id: str | None,
    target_volunteer: dict,
    context: dict,
) -> bool:
    """Decide whether ``requester_id`` may see ``target_volunteer`` data.

    Fasilitator: always allowed.
    Volunteer querying self: always allowed.
    Volunteer querying peer: only when ``settings.allow_peer_query`` is True.
    """
    if context.get("is_fasilitator"):
        return True
    if requester_id and target_volunteer.get("id") == requester_id:
        return True
    return bool(getattr(settings, "allow_peer_query", False))


def is_cross_volunteer_query(
    message: str, *, sender_volunteer: dict | None
) -> bool:
    """Cheap detection used by the router before any LLM call.

    Triggers on ``@username`` or keyword patterns like ``tugas Rizki``
    when the mentioned name is not the sender themselves.
    """
    if not message:
        return False

    raw_candidates: list[str] = [
        m.group(1) for m in _USERNAME_PATTERN.finditer(message)
    ]
    for m in _KEYWORD_NAME_PATTERN.finditer(message):
        name = (m.group(1) or m.group(2) or "").strip()
        if not name:
            continue
        first_token = name.lower().split()[0]
        if first_token in _SELF_PRONOUNS:
            continue
        raw_candidates.append(name)
    if not raw_candidates:
        return False

    if sender_volunteer is None:
        return True

    sender_name = (sender_volunteer.get("name") or "").lower().split()
    for cand in raw_candidates:
        cand_lower = cand.lower().strip().lstrip("@")
        if not cand_lower:
            continue
        if cand_lower in sender_name:
            continue
        if any(cand_lower == part for part in sender_name):
            continue
        return True
    return False
