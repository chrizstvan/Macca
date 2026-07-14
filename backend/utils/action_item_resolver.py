"""Action-item resolver — fasilitator mention → action_items row.

Mirrors :class:`backend.utils.volunteer_resolver.VolunteerResolver`: a
stateless helper injected with the Supabase client and (optionally) a bound
``call_claude`` LLM caller. Translates a free-form fasilitator mention of a
reminder target ("ingetin presensi", "challenge bebersih pantai") into the
underlying ``action_items`` record using the same 3-layer matching ladder the
volunteer resolver uses.

Used by the fasilitator reminder flow to pick which action item to remind
volunteers about, and to filter by reminder *type* when the fasilitator names
a category ("ingetin pre-test") rather than a specific item.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Reminder-type keyword map                                                    #
# --------------------------------------------------------------------------- #

# type_key → trigger words found in fasilitator messages. Order matters:
# first matching category wins (more specific keys before generic ones).
_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "challenge": ("challenge", "tantangan", "misi"),
    "submission": ("submit", "laporan", "kumpulin", "upload"),
    "kelas": ("kelas", "class", "sesi belajar", "materi"),
    "presensi": ("presensi", "absen", "kehadiran", "hadir"),
    "pre_test": ("pre test", "pre-test", "pretest", "tes awal"),
    "post_test": ("post test", "post-test", "posttest", "tes akhir"),
    "buku_saku": ("buku saku", "panduan", "handbook", "pocket book"),
    "tautan": ("tautan", "link", "form", "isi"),
}

# Columns selected for the lightweight semantic-match candidate list.
_LIST_COLUMNS = "id, title, type"
# Full row for resolved hits.
_FULL_COLUMNS = "*"

_SEMANTIC_PROMPT_TEMPLATE = (
    'Fasilitator menyebut: "{text}"\n'
    "Daftar action item aktif:\n"
    "{items}\n"
    "Mana yang paling dimaksud? Jawab HANYA judul persisnya, "
    'atau "TIDAK_ADA".'
)
_NO_MATCH_TOKEN = "TIDAK_ADA"


class ActionItemResolver:
    """Fasilitator mention → ``action_items`` row resolver.

    Stateless helper; instantiate per call or reuse. ``llm_caller`` is the
    bound ``call_claude`` method of any ``BaseAgent`` subclass and is only
    used by the semantic fallback (layer 3) of :meth:`find_by_mention`; omit
    it when only the exact/partial layers are needed.
    """

    def __init__(self, db_client: Any, *, llm_caller: Any = None) -> None:
        self._db = db_client
        self._llm = llm_caller

    # ------------------------------------------------------------------ #
    # Mention → action item                                              #
    # ------------------------------------------------------------------ #

    async def find_by_mention(
        self, text: str, type_hint: str | None = None
    ) -> dict | list[dict] | None:
        """Resolve a fasilitator mention to one row, many rows, or None.

        3-layer matching ladder (same shape as the volunteer resolver):

        1. Exact (case-insensitive) title match → single row.
        2. Partial title match (``ILIKE %text%``) → one row, or a list when
           ambiguous (caller asks for clarification).
        3. Claude semantic match against all active titles → single row.

        ``type_hint`` narrows every layer to one reminder ``type`` when set.
        """
        if not text or not text.strip():
            return None
        cleaned = text.strip()

        # Layer 1: exact title match (ilike without wildcards == case-insensitive eq).
        exact = self._active_query(_FULL_COLUMNS, type_hint).ilike(
            "title", cleaned
        ).execute().data or []
        if exact:
            return exact[0]

        # Layer 2: partial title match.
        partial = self._active_query(_FULL_COLUMNS, type_hint).ilike(
            "title", f"%{cleaned}%"
        ).execute().data or []
        if len(partial) == 1:
            return partial[0]
        if partial:
            return partial  # ambiguous — caller disambiguates

        # Layer 3: Claude semantic match over all active titles.
        return await self._semantic_match(cleaned, type_hint)

    async def _semantic_match(
        self, text: str, type_hint: str | None
    ) -> dict | None:
        """Last-resort LLM disambiguation against active action-item titles."""
        if self._llm is None:
            return None

        all_active = self._active_query(_LIST_COLUMNS, type_hint).execute().data or []
        if not all_active:
            return None

        items_str = "\n".join(
            f"- {a['title']} ({a.get('type', '')})" for a in all_active
        )
        prompt = _SEMANTIC_PROMPT_TEMPLATE.format(text=text, items=items_str)

        try:
            raw = await self._llm(
                prompt,
                [{"role": "user", "content": text}],
                max_tokens=60,
            )
        except Exception as exc:  # noqa: BLE001 — LLM failure must not crash resolve
            logger.warning("action-item semantic match failed: %s", exc)
            return None

        match = (raw or "").strip()
        if not match or match == _NO_MATCH_TOKEN:
            return None

        for a in all_active:
            if a["title"].strip().lower() == match.lower():
                full = (
                    self._db.table("action_items")
                    .select(_FULL_COLUMNS)
                    .eq("id", a["id"])
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                return full[0] if full else None
        return None

    # ------------------------------------------------------------------ #
    # Active-challenge listing (for volunteer guidance context)           #
    # ------------------------------------------------------------------ #

    def list_active_challenges(self, limit: int = 5) -> list[dict]:
        """Return ``type='challenge'`` rows that are inside their active window.

        A challenge is active when ``is_active`` (already filtered) AND today is
        within ``[start_date, deadline]``:

        * ``start_date`` NULL → active from creation (back-compat / no migration).
        * ``deadline`` NULL   → no end date.

        Used to inject the current challenge brief into volunteer-facing
        guidance — read only; scoring/submissions live outside the bot.
        """
        rows = self._active_query(_FULL_COLUMNS, "challenge").execute().data or []
        today = date.today().isoformat()

        def _in_window(r: dict) -> bool:
            start = str(r["start_date"])[:10] if r.get("start_date") else None
            end = str(r["deadline"])[:10] if r.get("deadline") else None
            if start and start > today:
                return False  # not started yet
            if end and end < today:
                return False  # past deadline
            return True

        return [r for r in rows if _in_window(r)][:limit]

    # ------------------------------------------------------------------ #
    # Reminder-type detection                                            #
    # ------------------------------------------------------------------ #

    async def detect_type_from_message(self, message: str) -> str | None:
        """Detect a reminder *type* from a fasilitator message, for filtering.

        ``"ingetin presensi"`` → ``"presensi"``,
        ``"ingetin isi pre-test"`` → ``"pre_test"``,
        ``"ingetin baca buku saku"`` → ``"buku_saku"``.

        Returns the matching ``type`` key or None. Pure keyword scan — async
        only to keep a uniform ``await``-able resolver interface.
        """
        if not message:
            return None
        msg = message.lower()
        for type_key, words in _TYPE_KEYWORDS.items():
            if any(w in msg for w in words):
                return type_key
        return None

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _active_query(self, columns: str, type_hint: str | None):
        """Base ``action_items`` query scoped to active rows (+ optional type)."""
        q = self._db.table("action_items").select(columns).eq("is_active", True)
        if type_hint:
            q = q.eq("type", type_hint)
        return q
