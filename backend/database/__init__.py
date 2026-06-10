"""Database layer: Supabase client and dataclass model definitions."""

from .supabase_client import db, test_connection
from .models import (
    ChatHistory,
    Mission,
    Notification,
    Report,
    Volunteer,
    VolunteerMission,
)

__all__ = [
    "db",
    "test_connection",
    "Volunteer",
    "Mission",
    "VolunteerMission",
    "Report",
    "ChatHistory",
    "Notification",
]
