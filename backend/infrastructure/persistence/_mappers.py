"""Dict ↔ domain-entity converters.

Supabase responses are plain dicts. Adapters use these helpers to keep
the row shape isolated from the domain layer. None checks live here so
the entities don't have to know about partial rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from backend.domain.entities.mission import Mission, MissionAssignment
from backend.domain.entities.report import Report
from backend.domain.entities.score import Score
from backend.domain.entities.volunteer import Volunteer
from backend.domain.value_objects.kg import Kg
from backend.domain.value_objects.phone import Phone
from backend.utils.date_utils import parse_iso_date, parse_iso_datetime


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _opt_uuid(value: Any) -> UUID | None:
    return None if value is None else _uuid(value)


def volunteer_from_row(row: dict[str, Any]) -> Volunteer:
    quota = float(row.get("quota_kg") or 0) or 0.01  # Kg invariant > 0
    return Volunteer(
        id=_uuid(row["id"]),
        name=row.get("name") or "",
        area=row.get("area") or "",
        quota_kg=Kg(quota),
        phone=Phone.try_parse(row.get("phone")),
        telegram_id=row.get("telegram_id"),
        is_active=bool(row.get("is_active", True)),
        team=list(row.get("team") or []),
        mission_query_count=int(row.get("mission_query_count") or 0),
        mission_query_reset_at=parse_iso_date(row.get("mission_query_reset_at")),
    )


def mission_from_row(row: dict[str, Any]) -> Mission:
    return Mission(
        id=_uuid(row["id"]),
        title=row.get("title") or "",
        description=row.get("description"),
        status=row.get("status") or "active",
        deadline=parse_iso_date(row.get("deadline")),
    )


def assignment_from_row(
    row: dict[str, Any], *, volunteer_id: UUID, mission_id: UUID
) -> MissionAssignment:
    quota = float(row.get("quota_kg") or 0) or 0.01
    reported = row.get("reported_kg")
    reported_kg = Kg(float(reported)) if reported and float(reported) > 0 else None
    return MissionAssignment(
        volunteer_id=volunteer_id,
        mission_id=mission_id,
        quota_kg=Kg(quota),
        assigned_area=row.get("assigned_area") or "",
        reported_kg=reported_kg,
    )


def report_from_row(row: dict[str, Any]) -> Report:
    return Report(
        id=_uuid(row["id"]),
        volunteer_id=_uuid(row["volunteer_id"]),
        mission_id=_uuid(row["mission_id"]),
        kg_collected=Kg(float(row["kg_collected"])),
        location=row.get("location") or "",
        photo_url=row.get("photo_url"),
        source=row.get("source") or "chat",
        verified=bool(row.get("verified", False)),
        is_flagged=bool(row.get("is_flagged", False)),
        flag_reason=row.get("flag_reason"),
        is_test=bool(row.get("is_test", False)),
        reported_at=parse_iso_datetime(row.get("reported_at")),
        extra_data=dict(row.get("extra_data") or {}),
    )


def report_to_row(report: Report) -> dict[str, Any]:
    payload = {
        "volunteer_id": str(report.volunteer_id),
        "mission_id": str(report.mission_id),
        "kg_collected": report.kg_collected.value,
        "location": report.location,
        "photo_url": report.photo_url,
        "source": report.source,
        "verified": report.verified,
        "is_flagged": report.is_flagged,
        "flag_reason": report.flag_reason,
        "is_test": report.is_test,
        "extra_data": report.extra_data,
    }
    # Let Postgres assign id + reported_at on insert when missing.
    if report.id is not None and not _is_sentinel_uuid(report.id):
        payload["id"] = str(report.id)
    return payload


def score_from_row(row: dict[str, Any]) -> Score:
    return Score(
        volunteer_id=_uuid(row["volunteer_id"]),
        impact_score=float(row.get("impact_score") or 0),
        quiz_score=float(row.get("quiz_score") or 0),
        rank=row.get("rank"),
        prev_rank=row.get("prev_rank"),
        last_updated=parse_iso_datetime(row.get("last_updated"))
        or datetime.now(timezone.utc),
    )


_SENTINEL_UUID = UUID("00000000-0000-0000-0000-000000000000")


def _is_sentinel_uuid(value: UUID) -> bool:
    return value == _SENTINEL_UUID


SENTINEL_UUID = _SENTINEL_UUID
