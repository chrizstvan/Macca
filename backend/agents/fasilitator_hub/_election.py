"""Election mixin — fasilitator triggers for the per-team election flow.

Iteration 1: detect "mulai pemilihan …" (approval gate) and
"ya mulai pencalonan …" (open nomination + blast). Delegates the actual work
to :mod:`backend.agents.election_handler`.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# "mulai/buat/bikin pemilihan [ketua] [kelompok] X"  OR  "pemilihan ketua X"
ELECTION_START_PATTERN = re.compile(
    r"^\s*(?:mulai|buat|bikin)\s+pemilihan\b(?P<tail1>.*)$"
    r"|^\s*pemilihan\s+ketua\b(?P<tail2>.*)$",
    re.IGNORECASE | re.DOTALL,
)
# "ya mulai pencalonan X"
ELECTION_CONFIRM_PATTERN = re.compile(
    r"^\s*ya\s+mulai\s+pencalonan\s+(?P<team>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "tutup pencalonan X"
ELECTION_CLOSE_PATTERN = re.compile(
    r"^\s*tutup\s+pencalonan\s+(?P<team>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "lanjut voting X"
ELECTION_VOTING_PATTERN = re.compile(
    r"^\s*(?:lanjut|mulai|buka)\s+voting\s+(?P<team>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "tutup voting X"
ELECTION_CLOSE_VOTE_PATTERN = re.compile(
    r"^\s*tutup\s+voting\s+(?P<team>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "sahkan hasil X"
ELECTION_FINALIZE_PATTERN = re.compile(
    r"^\s*sahkan\s+hasil\s+(?P<team>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "umumkan hasil X"
ELECTION_ANNOUNCE_PATTERN = re.compile(
    r"^\s*umumkan\s+hasil\s+(?P<team>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# "status pemilihan X" / "cek pemilihan X"
ELECTION_STATUS_PATTERN = re.compile(
    r"^\s*(?:status|cek)\s+pemilihan\s+(?P<team>.+)$",
    re.IGNORECASE | re.DOTALL,
)
# Filler words stripped when extracting the team name from the command tail.
_TEAM_FILLER = re.compile(r"\b(ketua|kelompok|kel|untuk|tim|grup|group)\b", re.IGNORECASE)


class ElectionMixin:
    """Fasilitator-facing election triggers (start + open nomination)."""

    @staticmethod
    def _is_election_start(message: str) -> bool:
        return bool(message and ELECTION_START_PATTERN.match(message))

    @staticmethod
    def _is_election_confirm(message: str) -> bool:
        return bool(message and ELECTION_CONFIRM_PATTERN.match(message))

    @staticmethod
    def _is_election_close(message: str) -> bool:
        return bool(message and ELECTION_CLOSE_PATTERN.match(message))

    @staticmethod
    def _is_election_voting(message: str) -> bool:
        return bool(message and ELECTION_VOTING_PATTERN.match(message))

    @staticmethod
    def _is_election_close_vote(message: str) -> bool:
        return bool(message and ELECTION_CLOSE_VOTE_PATTERN.match(message))

    @staticmethod
    def _is_election_finalize(message: str) -> bool:
        return bool(message and ELECTION_FINALIZE_PATTERN.match(message))

    @staticmethod
    def _is_election_announce(message: str) -> bool:
        return bool(message and ELECTION_ANNOUNCE_PATTERN.match(message))

    @staticmethod
    def _is_election_status(message: str) -> bool:
        return bool(message and ELECTION_STATUS_PATTERN.match(message))

    @staticmethod
    def _extract_election_team(raw: str) -> str:
        cleaned = _TEAM_FILLER.sub(" ", raw or "")
        return " ".join(cleaned.split()).strip()

    async def _resolve_team(self, phrase: str) -> str | None:
        """Match a loosely-typed team phrase to an actual volunteer team value."""
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )
        from backend.infrastructure.persistence._mappers import _coerce_team

        if not phrase:
            return None
        needle = phrase.strip().lower()
        rows = await build_volunteer_query_repository().list_all()
        teams = {
            (_coerce_team(v.get("team")) or "").strip()
            for v in rows
            if _coerce_team(v.get("team"))
        }
        # Exact (ci) first, then substring either direction.
        for t in teams:
            if t.lower() == needle:
                return t
        for t in teams:
            if needle in t.lower() or t.lower() in needle:
                return t
        return None

    async def _handle_election_start(self, message: str) -> str:
        from backend.agents.election_handler import start_election_request

        m = ELECTION_START_PATTERN.match(message)
        tail = (m.group("tail1") or m.group("tail2") or "") if m else ""
        phrase = self._extract_election_team(tail)
        if not phrase:
            return "Sebutkan kelompoknya ya, contoh: 'mulai pemilihan ketua kelompok BPJS'."
        team = await self._resolve_team(phrase) or phrase
        return await start_election_request(team, context={})

    async def _handle_election_confirm(self, message: str) -> str:
        from backend.agents.election_handler import open_nomination

        m = ELECTION_CONFIRM_PATTERN.match(message)
        phrase = self._extract_election_team((m.group("team") if m else "") or "")
        team = await self._resolve_team(phrase) or phrase
        return await open_nomination(team)

    async def _handle_election_close(self, message: str) -> str:
        from backend.agents.election_handler import close_nomination

        m = ELECTION_CLOSE_PATTERN.match(message)
        phrase = self._extract_election_team((m.group("team") if m else "") or "")
        team = await self._resolve_team(phrase) or phrase
        return await close_nomination(team)

    async def _handle_election_voting(self, message: str) -> str:
        from backend.agents.election_handler import open_voting

        m = ELECTION_VOTING_PATTERN.match(message)
        phrase = self._extract_election_team((m.group("team") if m else "") or "")
        team = await self._resolve_team(phrase) or phrase
        return await open_voting(team)

    async def _handle_election_close_vote(self, message: str) -> str:
        from backend.agents.election_handler import close_voting

        m = ELECTION_CLOSE_VOTE_PATTERN.match(message)
        phrase = self._extract_election_team((m.group("team") if m else "") or "")
        team = await self._resolve_team(phrase) or phrase
        return await close_voting(team)

    async def _handle_election_finalize(self, message: str) -> str:
        from backend.agents.election_handler import finalize_election

        m = ELECTION_FINALIZE_PATTERN.match(message)
        phrase = self._extract_election_team((m.group("team") if m else "") or "")
        team = await self._resolve_team(phrase) or phrase
        return await finalize_election(team)

    async def _handle_election_announce(self, message: str) -> str:
        from backend.agents.election_handler import announce_result

        m = ELECTION_ANNOUNCE_PATTERN.match(message)
        phrase = self._extract_election_team((m.group("team") if m else "") or "")
        team = await self._resolve_team(phrase) or phrase
        return await announce_result(team)

    async def _handle_election_status(self, message: str) -> str:
        from backend.agents.election_handler import show_election_status

        m = ELECTION_STATUS_PATTERN.match(message)
        phrase = self._extract_election_team((m.group("team") if m else "") or "")
        team = await self._resolve_team(phrase) or phrase
        return await show_election_status(team)
