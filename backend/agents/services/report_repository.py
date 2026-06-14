"""Supabase reads/writes for the ``reports`` table.

Kept tiny and dependency-free so the orchestrator agent can stay focused
on intent + flow. All functions are synchronous because Supabase-py is
sync; the agent wraps them inside ``async def`` methods.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.database.supabase_client import db

logger = logging.getLogger(__name__)


def _today_start_iso() -> str:
    """UTC midnight today, ISO-8601, used for ``reported_at >= start`` filters."""
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


def find_latest_today(volunteer_id: str, mission_id: str) -> dict | None:
    """Most recent report from this volunteer for this mission today, or None."""
    rows = (
        db.table("reports")
        .select("id, kg_collected, location, reported_at")
        .eq("volunteer_id", volunteer_id)
        .eq("mission_id", mission_id)
        .gte("reported_at", _today_start_iso())
        .order("reported_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def find_duplicate_today(
    volunteer_id: str, mission_id: str, kg: float
) -> dict | None:
    """Any report today within ±1 kg of ``kg`` (legacy similarity check)."""
    rows = (
        db.table("reports")
        .select("id, kg_collected")
        .eq("volunteer_id", volunteer_id)
        .eq("mission_id", mission_id)
        .gte("reported_at", _today_start_iso())
        .execute()
        .data
        or []
    )
    return next(
        (r for r in rows if abs(float(r["kg_collected"]) - kg) < 1), None
    )


def insert_report(payload: dict) -> dict | None:
    """Insert a single ``reports`` row; returns the row dict (or None)."""
    result = db.table("reports").insert(payload).execute()
    rows = result.data or []
    return rows[0] if rows else None


def update_report(report_id: str, update: dict) -> None:
    """Patch a single ``reports`` row."""
    db.table("reports").update(update).eq("id", report_id).execute()


def sync_reported_kg(volunteer_id: str, mission_id: str) -> float:
    """Recompute the volunteer's total kg + mirror it on ``volunteer_missions``.

    The ``reported_kg`` column on ``volunteer_missions`` was added in the
    Part-7 migration; older deployments may not have it yet. We log and
    swallow the error so reporting still succeeds in those environments.
    """
    rows = (
        db.table("reports")
        .select("kg_collected")
        .eq("volunteer_id", volunteer_id)
        .eq("mission_id", mission_id)
        .execute()
        .data
        or []
    )
    total = sum(float(r["kg_collected"]) for r in rows)
    try:
        (
            db.table("volunteer_missions")
            .update({"reported_kg": total})
            .eq("volunteer_id", volunteer_id)
            .eq("mission_id", mission_id)
            .execute()
        )
    except Exception as exc:
        logger.warning(
            "Could not update volunteer_missions.reported_kg: %s", exc
        )
    return total
