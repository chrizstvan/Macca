"""Read/write port for the ``elections`` state machine (per-team ketua/wakil).

Keeps the presentation layer (election handler / fasilitator-hub) off direct
``db.table(...)`` calls. Rows are plain dicts (query-side DTOs).
"""

from __future__ import annotations

from typing import Protocol


class ElectionRepository(Protocol):
    async def get_active(self, team: str) -> dict | None:
        """Latest non-``completed`` election for a team, or None."""
        ...

    async def create(self, *, team: str, status: str) -> dict:
        """Insert a new election row; return the created row."""
        ...

    async def get_nomination(
        self, *, election_id: str, nominator_id: str
    ) -> dict | None:
        """Existing nomination by this volunteer for this election, or None."""
        ...

    async def add_nomination(
        self,
        *,
        election_id: str,
        nominator_id: str,
        candidate_name: str,
        candidate_phone: str | None,
        candidate_volunteer_id: str | None,
    ) -> dict:
        """Insert a nomination. Raises on UNIQUE violation (already nominated)."""
        ...

    async def update_status(self, *, election_id: str, status: str) -> None:
        """Move an election to a new status."""
        ...

    async def list_nominations(self, *, election_id: str) -> list[dict]:
        """All nomination rows for an election (tally done in Python)."""
        ...

    async def add_finalist(
        self,
        *,
        election_id: str,
        candidate_phone: str | None,
        candidate_name: str,
        nomination_count: int,
        slot_number: int,
    ) -> None:
        """Persist one top-N finalist row."""
        ...

    async def get_finalists(self, *, election_id: str) -> list[dict]:
        """Finalist rows ordered by slot_number."""
        ...

    async def get_vote(
        self, *, election_id: str, voter_id: str
    ) -> dict | None:
        """Existing vote by this volunteer for this election, or None."""
        ...

    async def add_vote(
        self,
        *,
        election_id: str,
        voter_id: str,
        candidate_phone: str | None,
        candidate_name: str,
    ) -> dict:
        """Insert a vote. Raises on UNIQUE violation (already voted)."""
        ...

    async def list_votes(self, *, election_id: str) -> list[dict]:
        """All vote rows for an election (tally done in Python)."""
        ...

    async def get_latest(self, team: str) -> dict | None:
        """Most recent election for a team (any status), or None."""
        ...

    async def set_result(
        self,
        *,
        election_id: str,
        ketua_name: str | None,
        ketua_phone: str | None,
        wakil_name: str | None,
        wakil_phone: str | None,
        status: str,
    ) -> None:
        """Persist ketua/wakil + move to a terminal status (e.g. completed)."""
        ...
