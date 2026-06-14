"""Domain-specific exception hierarchy.

Errors raised by entities/value objects when business invariants are
violated. Distinguished from infrastructure errors (network failures,
DB errors) so adapters and use cases can react differently.
"""


class DomainError(Exception):
    """Base class for any business-rule violation."""


class InvalidPhone(DomainError):
    """Phone number could not be parsed into the E.164-ish canonical form."""


class InvalidKg(DomainError):
    """Reported weight is outside the acceptable range (0 < kg ≤ 999)."""


class VolunteerNotRegistered(DomainError):
    """A request mentioned a volunteer who is not in the registry."""


class MissionNotActive(DomainError):
    """The volunteer has no active mission to report against."""


class QuotaExceeded(DomainError):
    """Volunteer reached a per-day usage cap (e.g. mission_briefing limit)."""
