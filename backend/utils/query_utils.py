"""Shared Supabase query helpers used by agents and the ranking calculator.

Centralises three duplicated lookups:

* ``get_active_mission(volunteer_id)`` — returns the active mission (and the
  matching assignment row) for a volunteer.
* ``find_volunteers_by_name(name)`` — case-insensitive partial match used by
  ``/test_as`` and friends.
* ``find_target_volunteer(message, volunteers)`` — picks the volunteer
  whose name token appears in a free-form fasilitator message.
"""

from __future__ import annotations

from backend.database.supabase_client import db


def get_active_mission(
    volunteer_id: str, *, with_assignment: bool = False
) -> dict | None | tuple[dict | None, dict | None]:
    """Return the active mission for ``volunteer_id``.

    With ``with_assignment=True`` the call returns a ``(mission, assignment)``
    tuple — the assignment row carries ``quota_kg`` and ``assigned_area``
    that callers often need alongside the mission record. The mission dict
    is enriched with ``quota_kg`` and ``assigned_area`` from the assignment
    so single-return callers don't need to merge them themselves.
    """
    rows = (
        db.table("volunteer_missions")
        .select("quota_kg, assigned_area, missions(*)")
        .eq("volunteer_id", volunteer_id)
        .execute()
        .data
        or []
    )
    for row in rows:
        mission = row.get("missions")
        if mission and mission.get("status") == "active":
            mission["quota_kg"] = row.get("quota_kg")
            mission["assigned_area"] = row.get("assigned_area")
            if with_assignment:
                return mission, row
            return mission
    if with_assignment:
        return None, None
    return None


def find_volunteers_by_name(name: str) -> list[dict]:
    """Case-insensitive partial-name lookup; returns id/name/area/quota_kg."""
    if not name:
        return []
    result = (
        db.table("volunteers")
        .select("id, name, area, quota_kg")
        .ilike("name", f"%{name}%")
        .execute()
    )
    return result.data or []


def find_target_volunteer(
    message: str, volunteers: list[dict]
) -> dict | None:
    """Pick the first volunteer whose name token appears as a word in ``message``.

    Tokens shorter than 3 characters are ignored to avoid spurious matches
    (e.g. "an", "di").
    """
    padded = f" {message.lower()} "
    for volunteer in volunteers:
        name = (volunteer.get("name") or "").strip().lower()
        if not name:
            continue
        for token in name.split():
            if len(token) > 2 and f" {token} " in padded:
                return volunteer
    return None
