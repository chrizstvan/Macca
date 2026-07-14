"""Volunteer-persona mission briefing use case.

Equivalent to the legacy ``MissionBriefingAgent.process`` volunteer path
but expressed as orchestration on top of the domain + ports. The agent
becomes a thin presentation layer that translates the outcome into the
WhatsApp/Telegram reply text.

Daily mission-query rate limit is enforced by the ``Volunteer`` entity
itself — the use case just persists the new counter via the repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from backend.application.ports.chat_history_repository import ChatHistoryRepository
from backend.application.ports.clock import Clock
from backend.application.ports.llm_client import LLMClient
from backend.application.ports.mission_repository import MissionRepository
from backend.application.ports.report_repository import ReportRepository
from backend.application.ports.volunteer_repository import VolunteerRepository
from backend.application.use_cases._prompts import (
    BASE_BRIEFING_PROMPT,
    NO_ACTIVE_MISSION_HINT,
    SOP_SECTION,
)
from backend.domain.entities.mission import Mission, MissionAssignment
from backend.domain.entities.volunteer import Volunteer

DAILY_LIMIT = 2
HISTORY_LIMIT = 10
AGENT_MODULE = "mission_briefing"


# --------------------------------------------------------------------------- #
# Outcome ADT                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Brief:
    text: str
    is_last_free_query: bool


@dataclass(frozen=True)
class QuotaCapped:
    pass


@dataclass(frozen=True)
class NotRegistered:
    pass


BriefOutcome = Brief | QuotaCapped | NotRegistered


# --------------------------------------------------------------------------- #
# Use case                                                                      #
# --------------------------------------------------------------------------- #


@dataclass
class BriefMission:
    volunteers: VolunteerRepository
    missions: MissionRepository
    reports: ReportRepository
    history: ChatHistoryRepository
    llm: LLMClient
    clock: Clock
    # Optional — when wired by the composition root, the system prompt
    # includes a team rollup line for team-mode volunteers.
    teams: Any = None

    async def execute(
        self,
        *,
        volunteer_id: UUID,
        message: str,
        telegram_id: int | None = None,
        challenge_context: str = "",
    ) -> BriefOutcome:
        volunteer = await self.volunteers.get_by_id(volunteer_id)
        if volunteer is None:
            return NotRegistered()

        today = self.clock.today()
        count_before = volunteer.mission_query_count
        if not volunteer.consume_mission_query(daily_limit=DAILY_LIMIT, today=today):
            return QuotaCapped()
        await self.volunteers.save(volunteer)

        active = await self.missions.get_active_for(volunteer.id)
        mission: Mission | None
        assignment: MissionAssignment | None
        if active is None:
            mission, assignment = None, None
        else:
            mission, assignment = active

        progress_kg = (
            await self.reports.total_kg_for(volunteer.id, mission.id)
            if mission is not None
            else 0.0
        )

        team_progress = None
        if (
            self.teams is not None
            and volunteer.is_team_mode
            and mission is not None
        ):
            try:
                team_progress = await self.teams.get_progress(
                    team=volunteer.team or "", mission_id=mission.id
                )
            except Exception:
                team_progress = None

        challenge_suffix = f"\n\n{challenge_context}" if challenge_context else ""
        system_prompt = self._build_system_prompt(
            volunteer=volunteer,
            mission=mission,
            assignment=assignment,
            progress_kg=progress_kg,
            today=today,
            team_progress=team_progress,
        ) + challenge_suffix

        history = await self.history.get_recent(
            telegram_id, limit=HISTORY_LIMIT
        )
        messages: list[dict[str, Any]] = list(history) + [
            {"role": "user", "content": message}
        ]
        reply = await self.llm.complete(
            system=system_prompt, messages=messages, max_tokens=1000
        )

        await self.history.save_turn(
            telegram_id, role="user", content=message, agent_module=AGENT_MODULE
        )
        await self.history.save_turn(
            telegram_id, role="assistant", content=reply, agent_module=AGENT_MODULE
        )

        is_last_free = count_before == DAILY_LIMIT - 1
        return Brief(text=reply, is_last_free_query=is_last_free)

    # ------------------------------------------------------------------ #
    # Prompt assembly                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_system_prompt(
        *,
        volunteer: Volunteer,
        mission: Mission | None,
        assignment: MissionAssignment | None,
        progress_kg: float,
        today: date,
        team_progress: Any = None,
    ) -> str:
        team_label = (
            volunteer.team if volunteer.is_team_mode else "—"
        )
        mode_label = "Tim" if volunteer.is_team_mode else "Individu"
        quota = (
            assignment.quota_kg.value
            if assignment is not None
            else volunteer.quota_kg.value
        )
        area = (
            assignment.assigned_area
            if assignment is not None
            else volunteer.area or "-"
        )

        volunteer_section = (
            "Data volunteer:\n"
            f"- Nama: {volunteer.name}\n"
            f"- Area tugas: {area}\n"
            f"- Mode misi: {mode_label}\n"
            f"- Tim: {team_label}\n"
            f"- Kuota: {quota:g} kg"
        )
        if team_progress is not None and getattr(team_progress, "member_count", 0):
            volunteer_section += (
                "\n- Rollup tim: "
                f"{team_progress.reported_kg:g}/{team_progress.total_quota_kg:g} kg "
                f"({team_progress.pct:.0f}%) — {team_progress.member_count} anggota"
            )

        if mission is not None:
            remaining = mission.days_until_deadline(today)
            remaining_text = (
                f"{remaining} hari lagi"
                if remaining is not None and remaining >= 0
                else "sudah lewat"
                if remaining is not None
                else "tidak diketahui"
            )
            mission_section = (
                "Misi aktif:\n"
                f"- Judul: {mission.title}\n"
                f"- Deskripsi: {mission.description or '-'}\n"
                f"- Deadline: {mission.deadline} ({remaining_text})\n"
                f"- Progress {volunteer.name}: {progress_kg:g} kg "
                f"dari kuota {quota:g} kg"
            )
        else:
            mission_section = NO_ACTIVE_MISSION_HINT

        return (
            f"{BASE_BRIEFING_PROMPT}\n\n"
            f"{volunteer_section}\n\n"
            f"{mission_section}\n\n"
            f"{SOP_SECTION}"
        )
