"""Supabase-backed ElectionRepository — per-team election state machine."""

from __future__ import annotations

from supabase import Client

from backend.application.ports.election_repository import ElectionRepository


class SupabaseElectionRepository(ElectionRepository):
    def __init__(self, db: Client) -> None:
        self._db = db

    async def get_active(self, team: str) -> dict | None:
        rows = (
            self._db.table("elections")
            .select("*")
            .eq("team", team)
            .not_.in_("status", ["completed", "cancelled"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def create(self, *, team: str, status: str) -> dict:
        rows = (
            self._db.table("elections")
            .insert({"team": team, "status": status})
            .execute()
            .data
            or []
        )
        return rows[0] if rows else {"team": team, "status": status}

    async def get_nomination(
        self, *, election_id: str, nominator_id: str
    ) -> dict | None:
        rows = (
            self._db.table("election_nominations")
            .select("*")
            .eq("election_id", election_id)
            .eq("nominator_volunteer_id", nominator_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def add_nomination(
        self,
        *,
        election_id: str,
        nominator_id: str,
        candidate_name: str,
        candidate_phone: str | None,
        candidate_volunteer_id: str | None,
    ) -> dict:
        rows = (
            self._db.table("election_nominations")
            .insert(
                {
                    "election_id": election_id,
                    "nominator_volunteer_id": nominator_id,
                    "candidate_name": candidate_name,
                    "candidate_phone": candidate_phone,
                    "candidate_volunteer_id": candidate_volunteer_id,
                }
            )
            .execute()
            .data
            or []
        )
        return rows[0] if rows else {}

    async def update_status(self, *, election_id: str, status: str) -> None:
        self._db.table("elections").update({"status": status}).eq(
            "id", election_id
        ).execute()

    async def list_nominations(self, *, election_id: str) -> list[dict]:
        return (
            self._db.table("election_nominations")
            .select("*")
            .eq("election_id", election_id)
            .execute()
            .data
            or []
        )

    async def add_finalist(
        self,
        *,
        election_id: str,
        candidate_phone: str | None,
        candidate_name: str,
        nomination_count: int,
        slot_number: int,
    ) -> None:
        self._db.table("election_finalists").insert(
            {
                "election_id": election_id,
                "candidate_phone": candidate_phone,
                "candidate_name": candidate_name,
                "nomination_count": nomination_count,
                "slot_number": slot_number,
            }
        ).execute()

    async def get_finalists(self, *, election_id: str) -> list[dict]:
        return (
            self._db.table("election_finalists")
            .select("*")
            .eq("election_id", election_id)
            .order("slot_number")
            .execute()
            .data
            or []
        )

    async def get_vote(
        self, *, election_id: str, voter_id: str
    ) -> dict | None:
        rows = (
            self._db.table("election_votes")
            .select("*")
            .eq("election_id", election_id)
            .eq("voter_volunteer_id", voter_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    async def add_vote(
        self,
        *,
        election_id: str,
        voter_id: str,
        candidate_phone: str | None,
        candidate_name: str,
    ) -> dict:
        rows = (
            self._db.table("election_votes")
            .insert(
                {
                    "election_id": election_id,
                    "voter_volunteer_id": voter_id,
                    "candidate_phone": candidate_phone,
                    "candidate_name": candidate_name,
                }
            )
            .execute()
            .data
            or []
        )
        return rows[0] if rows else {}

    async def list_votes(self, *, election_id: str) -> list[dict]:
        return (
            self._db.table("election_votes")
            .select("*")
            .eq("election_id", election_id)
            .execute()
            .data
            or []
        )

    async def get_latest(self, team: str) -> dict | None:
        rows = (
            self._db.table("elections")
            .select("*")
            .eq("team", team)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

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
        self._db.table("elections").update(
            {
                "ketua_name": ketua_name,
                "ketua_phone": ketua_phone,
                "wakil_name": wakil_name,
                "wakil_phone": wakil_phone,
                "status": status,
            }
        ).eq("id", election_id).execute()
