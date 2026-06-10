"""Pydantic models representing Macca database entities."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MissionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VolunteerStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class Mission(BaseModel):
    """Represents a volunteer mission in the database."""

    id: UUID | None = None
    title: str
    description: str
    location: str
    status: MissionStatus = MissionStatus.DRAFT
    required_volunteers: int = 1
    start_date: datetime | None = None
    end_date: datetime | None = None
    fasilitator_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Volunteer(BaseModel):
    """Represents a volunteer registered on the platform."""

    id: UUID | None = None
    telegram_id: str
    username: str = ""
    full_name: str = ""
    status: VolunteerStatus = VolunteerStatus.ACTIVE
    skills: list[str] = Field(default_factory=list)
    missions_completed: int = 0
    total_hours: float = 0.0
    joined_at: datetime | None = None


class ProgressUpdate(BaseModel):
    """A progress report submitted by a volunteer for a specific mission."""

    id: UUID | None = None
    mission_id: UUID
    volunteer_id: UUID
    message: str
    completion_pct: int = Field(ge=0, le=100, default=0)
    image_url: str | None = None
    needs_escalation: bool = False
    created_at: datetime | None = None


class ImpactReport(BaseModel):
    """Aggregated impact data for a completed or in-progress mission."""

    id: UUID | None = None
    mission_id: UUID
    people_helped: int = 0
    volunteer_hours: float = 0.0
    resources_distributed: dict[str, Any] = Field(default_factory=dict)
    impact_score: float = 0.0
    narrative: str = ""
    generated_at: datetime | None = None
