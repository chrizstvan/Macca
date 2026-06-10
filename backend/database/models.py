"""Dataclass models mirroring the Supabase schema (see schema.sql)."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class Volunteer:
    """A registered volunteer assigned to a kelurahan area."""

    telegram_id: int
    name: str
    area: str
    id: UUID | None = None
    phone: str | None = None
    team: list[str] = field(default_factory=list)
    quota_kg: float = 20.0
    joined_at: datetime | None = None
    is_active: bool = True


@dataclass
class Mission:
    """A collection mission with a deadline and lifecycle status."""

    title: str
    deadline: datetime
    id: UUID | None = None
    description: str | None = None
    status: str = "active"  # active / completed / cancelled
    created_at: datetime | None = None
    created_by: str | None = None


@dataclass
class VolunteerMission:
    """Junction record assigning a volunteer to a mission with a quota and area."""

    volunteer_id: UUID
    mission_id: UUID
    quota_kg: float
    assigned_area: str
    id: UUID | None = None


@dataclass
class Report:
    """A collection report submitted by a volunteer for a mission."""

    volunteer_id: UUID
    mission_id: UUID
    kg_collected: float
    location: str
    id: UUID | None = None
    photo_url: str | None = None
    raw_message: str | None = None
    is_flagged: bool = False
    flag_reason: str | None = None
    reported_at: datetime | None = None
    verified: bool = False


@dataclass
class ChatHistory:
    """A single message in a volunteer's conversation history."""

    telegram_id: int
    role: str  # user / assistant
    content: str
    id: UUID | None = None
    agent_module: str | None = None
    created_at: datetime | None = None


@dataclass
class Notification:
    """An outbound notification queued for or sent to a Telegram user."""

    telegram_id: int
    type: str  # reminder / alert / broadcast
    message: str
    id: UUID | None = None
    sent_at: datetime | None = None
    status: str = "pending"
