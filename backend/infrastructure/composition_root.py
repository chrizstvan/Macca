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
from backend.application.use_cases.broadcast_quiz_now import BroadcastQuizNow
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
from .persistence.supabase_fasilitator_context_repo import (
    SupabaseFasilitatorContextRepository,
)
from .persistence.supabase_mission_repo import SupabaseMissionRepository
from .persistence.supabase_report_repo import SupabaseReportRepository
from .persistence.supabase_content_draft_repo import (
    SupabaseContentDraftRepository,
)
from .persistence.supabase_election_repo import SupabaseElectionRepository
from .persistence.supabase_quiz_draft_repo import SupabaseQuizDraftRepository
from .persistence.supabase_scheduled_message_repo import (
    SupabaseScheduledMessageRepository,
)
from .persistence.supabase_team_repo import SupabaseTeamRepository
from .persistence.supabase_volunteer_query_repo import (
    SupabaseVolunteerQueryRepository,
)
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


def build_broadcast_quiz_now() -> BroadcastQuizNow:
    """Broadcast an approved quiz spec now + create its active_quizzes row."""
    return BroadcastQuizNow(
        volunteers=SupabaseVolunteerRepository(db),
        quizzes=SupabaseActiveQuizRepository(db),
        notifier=_notifier(),
    )


def build_quiz_draft_repository() -> SupabaseQuizDraftRepository:
    """Read/write draft-quiz store (``quizzes`` table, draft→approved→sent)."""
    return SupabaseQuizDraftRepository(db)


def build_content_draft_repository() -> SupabaseContentDraftRepository:
    """Read/write draft-only content store (``content_drafts`` table)."""
    return SupabaseContentDraftRepository(db)


def build_scheduled_message_repository() -> SupabaseScheduledMessageRepository:
    """Read/write the ``scheduled_messages`` dispatch queue."""
    return SupabaseScheduledMessageRepository(db)


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


def build_chat_history_repository() -> SupabaseChatHistoryRepository:
    """Read/write chat_history repo for agent conversation persistence."""
    return SupabaseChatHistoryRepository(db)


def build_report_repository() -> SupabaseReportRepository:
    """Read/write reports repo for agent inquiry + status paths."""
    return SupabaseReportRepository(db)


def build_mission_repository() -> SupabaseMissionRepository:
    """Read/write missions + assignments repo for agent inquiry + status paths."""
    return SupabaseMissionRepository(db)


def build_fasilitator_context_repository() -> SupabaseFasilitatorContextRepository:
    """Key/value store for fasilitator config (e.g. project description)."""
    return SupabaseFasilitatorContextRepository(db)


def build_volunteer_query_repository() -> SupabaseVolunteerQueryRepository:
    """Read-model volunteer lookups (dict DTOs) for agent + channel read paths."""
    return SupabaseVolunteerQueryRepository(db)


def build_election_repository() -> SupabaseElectionRepository:
    """Read/write the ``elections`` per-team state machine."""
    return SupabaseElectionRepository(db)


__all__ = [
    "build_submit_report",
    "build_brief_mission",
    "build_send_weekly_plastic_fact",
    "build_send_mission_education_brief",
    "build_send_weekly_quiz",
    "build_handle_quiz_answer",
    "build_broadcast_quiz_now",
    "build_quiz_draft_repository",
    "build_content_draft_repository",
    "build_scheduled_message_repository",
    "build_handle_inbound_contact",
    "build_team_repository",
    "build_chat_history_repository",
    "build_report_repository",
    "build_mission_repository",
    "build_fasilitator_context_repository",
    "build_volunteer_query_repository",
    "build_election_repository",
]
