"""Report entity — a single plastic-collection submission.

The duplicate-clarification verdict logic lives here because it's pure
business logic (no DB, no LLM) and trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from backend.domain.value_objects.kg import Kg


CLEAR_DUPLICATE_KG_TOLERANCE = 1.0
AMBIGUOUS_KG_UPPER_BOUND = 5.0


class DuplicateVerdict(str, Enum):
    CLEAR_DUPLICATE = "clear_duplicate"
    AMBIGUOUS = "ambiguous"
    LIKELY_ADDITION = "likely_addition"


@dataclass
class Report:
    id: UUID
    volunteer_id: UUID
    mission_id: UUID
    kg_collected: Kg
    location: str
    photo_url: str | None
    source: str
    verified: bool = False
    is_flagged: bool = False
    flag_reason: str | None = None
    is_test: bool = False
    reported_at: datetime | None = None
    extra_data: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def _same_location(a: str, b: str) -> bool:
        la, lb = a.lower(), b.lower()
        return la in lb or lb in la

    def classify_against(self, existing: "Report") -> DuplicateVerdict:
        """Classify this candidate report relative to an earlier one today.

        Mirrors the 3-tier classifier in progress_tracker.validate_and_save
        but here as pure domain logic — no DB lookup, no LLM, no IO.
        """
        diff = self.kg_collected.diff(existing.kg_collected)
        same_loc = self._same_location(self.location, existing.location)

        if diff < CLEAR_DUPLICATE_KG_TOLERANCE and same_loc:
            return DuplicateVerdict.CLEAR_DUPLICATE
        if diff >= AMBIGUOUS_KG_UPPER_BOUND or not same_loc:
            return DuplicateVerdict.LIKELY_ADDITION
        return DuplicateVerdict.AMBIGUOUS

    def flag(self, reason: str) -> None:
        """Append a reason and mark this report as needing fasilitator review."""
        if self.flag_reason:
            self.flag_reason = f"{self.flag_reason} | {reason}"
        else:
            self.flag_reason = reason
        self.is_flagged = True
