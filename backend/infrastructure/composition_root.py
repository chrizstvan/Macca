"""Composition root: the only place that knows concrete adapter classes.

FastAPI routes / agents that want to use a use case import a *builder*
from here, never the adapter classes directly. Keeps the dependency
graph honest: ``application`` and ``domain`` never import infrastructure.
"""

from __future__ import annotations

from functools import lru_cache

from backend.application.use_cases.brief_mission import BriefMission
from backend.application.use_cases.handle_inbound_contact import (
    HandleInboundContact,
)
from backend.application.use_cases.handle_quiz_answer import HandleQuizAnswer
from backend.application.use_cases.send_mission_education_brief import (
    SendMissionEducationBrief,
)
from backend.application.use_cases.send_weekly_fact import SendWeeklyPlasticFact
from backend.application.use_cases.send_weekly_quiz import SendWeeklyQuiz
from backend.application.use_cases.submit_report import SubmitReport
from backend.config import settings
from backend.database.supabase_client import db

from .llm.anthropic_client import AnthropicLLMClient
from .notifier.channel_notifier import ChannelNotifier
from .persistence.supabase_active_quiz_repo import SupabaseActiveQuizRepository
from .persistence.supabase_unknown_contact_repo import (
    SupabaseUnknownContactRepository,
)
from .persistence.supabase_chat_history_repo import (
    SupabaseChatHistoryRepository,
)
from .persistence.supabase_mission_repo import SupabaseMissionRepository
from .persistence.supabase_report_repo import SupabaseReportRepository
from .persistence.supabase_team_repo import SupabaseTeamRepository
from .persistence.supabase_volunteer_repo import SupabaseVolunteerRepository
from .system.utc_clock import UtcClock
from .vision.photo_verifier_adapter import ClaudePhotoVerifier


@lru_cache(maxsize=1)
def _clock() -> UtcClock:
    return UtcClock()


@lru_cache(maxsize=1)
def _llm() -> AnthropicLLMClient:
    return AnthropicLLMClient(
        settings.anthropic_api_key,
        default_model=settings.claude_default_model,
        default_max_tokens=settings.default_max_tokens,
    )


def build_submit_report() -> SubmitReport:
    return SubmitReport(
        volunteers=SupabaseVolunteerRepository(db),
        missions=SupabaseMissionRepository(db),
        reports=SupabaseReportRepository(db),
        photos=ClaudePhotoVerifier(),
        clock=_clock(),
    )


def build_brief_mission() -> BriefMission:
    return BriefMission(
        teams=SupabaseTeamRepository(db),
        volunteers=SupabaseVolunteerRepository(db),
        missions=SupabaseMissionRepository(db),
        reports=SupabaseReportRepository(db),
        history=SupabaseChatHistoryRepository(db),
        llm=_llm(),
        clock=_clock(),
    )


@lru_cache(maxsize=1)
def _notifier() -> ChannelNotifier:
    return ChannelNotifier()


def build_send_weekly_plastic_fact() -> SendWeeklyPlasticFact:
    return SendWeeklyPlasticFact(
        volunteers=SupabaseVolunteerRepository(db),
        notifier=_notifier(),
        clock=_clock(),
    )


def build_send_mission_education_brief() -> SendMissionEducationBrief:
    return SendMissionEducationBrief(
        volunteers=SupabaseVolunteerRepository(db),
        notifier=_notifier(),
    )


def build_send_weekly_quiz() -> SendWeeklyQuiz:
    return SendWeeklyQuiz(
        volunteers=SupabaseVolunteerRepository(db),
        quizzes=SupabaseActiveQuizRepository(db),
        notifier=_notifier(),
        clock=_clock(),
    )


def build_handle_quiz_answer() -> HandleQuizAnswer:
    return HandleQuizAnswer(quizzes=SupabaseActiveQuizRepository(db))


def build_handle_inbound_contact() -> HandleInboundContact:
    return HandleInboundContact(
        volunteers=SupabaseVolunteerRepository(db),
        missions=SupabaseMissionRepository(db),
        reports=SupabaseReportRepository(db),
        unknown_contacts=SupabaseUnknownContactRepository(db),
        notifier=_notifier(),
        clock=_clock(),
    )


def build_team_repository() -> SupabaseTeamRepository:
    """Read-only team-aggregate repo for confirmation / brief / status text."""
    return SupabaseTeamRepository(db)


__all__ = [
    "build_submit_report",
    "build_brief_mission",
    "build_send_weekly_plastic_fact",
    "build_send_mission_education_brief",
    "build_send_weekly_quiz",
    "build_handle_quiz_answer",
    "build_handle_inbound_contact",
    "build_team_repository",
]
