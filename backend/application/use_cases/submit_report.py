"""Submit-a-plastic-collection-report use case.

Pure orchestration on top of the domain entities + repository ports.
No DB driver imports, no LLM SDK imports, no httpx — those live in
``backend.infrastructure`` and are injected via the constructor.

Mirrors the legacy ``ProgressTrackerAgent.validate_and_save`` flow but
without any of the agent/context/Claude/notification coupling:

    1. Look up active mission for the volunteer.
    2. Wrap inputs in domain value objects (raises on invalid weight).
    3. Apply quota + location flag checks.
    4. Find latest report today → classify_against → verdict.
    5. Photo verification gate.
    6. Persist + mirror total kg.

Caller decides what to do with the returned dataclass (send WhatsApp
reply, queue a fasilitator alert, draft a UI confirmation, …).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from backend.application.ports.clock import Clock
from backend.application.ports.mission_repository import MissionRepository
from backend.application.ports.photo_verifier import PhotoVerifier
from backend.application.ports.report_repository import ReportRepository
from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.domain.entities.report import DuplicateVerdict, Report
from backend.domain.errors import (
    InvalidKg,
    MissionNotActive,
    VolunteerNotRegistered,
)
from backend.domain.value_objects.kg import Kg


# --------------------------------------------------------------------------- #
# Outcome ADT — Pythonic tagged-union via dataclasses.                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Saved:
    """The report was persisted; ``report`` is the canonical row + ``total_kg``."""

    report: Report
    total_kg: float


@dataclass(frozen=True)
class NeedsPhoto:
    """``require_photo=True`` was set and no photo was attached."""

    message: str


@dataclass(frozen=True)
class PhotoRejected:
    """The vision verifier returned ``verdict='fail'``."""

    reason: str


@dataclass(frozen=True)
class DuplicateClarificationNeeded:
    """A near-identical report exists; caller must ask the user."""

    verdict: DuplicateVerdict
    existing: Report
    candidate: Report


SubmitOutcome = (
    Saved | NeedsPhoto | PhotoRejected | DuplicateClarificationNeeded
)


# --------------------------------------------------------------------------- #
# Use case                                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class SubmitReport:
    volunteers: VolunteerRepository
    missions: MissionRepository
    reports: ReportRepository
    photos: PhotoVerifier
    clock: Clock

    async def execute(
        self,
        *,
        volunteer_id: UUID,
        kg_value: float,
        location: str,
        source: str,
        photo_url: str | None = None,
        is_test: bool = False,
        skip_duplicate_check: bool = False,
        extra_data: dict[str, Any] | None = None,
        require_photo: bool = True,
    ) -> SubmitOutcome:
        volunteer = await self.volunteers.get_by_id(volunteer_id)
        if volunteer is None:
            raise VolunteerNotRegistered(str(volunteer_id))

        active = await self.missions.get_active_for(volunteer.id)
        if active is None:
            raise MissionNotActive(str(volunteer.id))
        mission, assignment = active

        try:
            kg = Kg(float(kg_value))
        except (TypeError, ValueError) as exc:
            raise InvalidKg(f"could not parse kg: {kg_value!r}") from exc

        candidate = Report(
            id=uuid4(),
            volunteer_id=volunteer.id,
            mission_id=mission.id,
            kg_collected=kg,
            location=location,
            photo_url=photo_url,
            source=source,
            verified=source == "fasilitator_relay",
            is_test=is_test,
            extra_data=dict(extra_data or {}),
        )

        # Quota threshold flag
        quota = assignment.quota_kg.value
        if quota and kg.value > quota * 2:
            candidate.flag(
                f"Berat {kg.value:g}kg melebihi 2x kuota ({quota:g}kg)"
            )

        # Location vs assigned area
        if assignment.assigned_area and not Report._same_location(
            assignment.assigned_area, location
        ):
            candidate.flag(
                f"Lokasi '{location}' di luar area tugas "
                f"'{assignment.assigned_area}'"
            )

        # Duplicate clarification (skip when caller already resolved it)
        if not skip_duplicate_check:
            existing = await self.reports.find_latest_today(
                volunteer.id, mission.id
            )
            if existing is not None:
                verdict = candidate.classify_against(existing)
                if verdict in {
                    DuplicateVerdict.CLEAR_DUPLICATE,
                    DuplicateVerdict.AMBIGUOUS,
                }:
                    return DuplicateClarificationNeeded(
                        verdict=verdict,
                        existing=existing,
                        candidate=candidate,
                    )
                # likely_addition → fall through and save normally

        # Photo verification gate
        is_relay = source == "fasilitator_relay"
        photo_result = await self.photos.verify_or_skip(
            photo_url=photo_url,
            reported_kg=kg.value,
            volunteer_area=volunteer.area,
            is_fasilitator_relay=is_relay,
            require_photo=require_photo,
        )

        if photo_result.get("needs_photo"):
            return NeedsPhoto(message=photo_result.get("message", ""))

        if photo_result.get("verdict") == "fail":
            return PhotoRejected(
                reason=photo_result.get("reason_id") or "Foto ditolak"
            )

        if photo_result.get("should_flag"):
            reason = photo_result.get("flag_reason")
            if reason:
                candidate.flag(reason)

        candidate.extra_data["photo_verification"] = photo_result

        saved = await self.reports.insert(candidate)
        total = await self.reports.total_kg_for(volunteer.id, mission.id)
        await self.missions.update_reported_kg(
            volunteer_id=volunteer.id,
            mission_id=mission.id,
            total_kg=total,
        )
        return Saved(report=saved, total_kg=total)
