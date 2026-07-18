"""Thin HTTP client for the Macca FastAPI admin endpoints.

Every action the dashboard triggers goes through the backend (instead of
talking to Supabase / WhatsApp directly) so the same business rules,
logging, and audit trail apply whether the request comes from chat, a
scheduled job, or the dashboard.

This module intentionally exposes flat functions instead of an HTTP-client
class — Streamlit pages already carry their own UI state; a class wrapper
would just add ceremony without enabling reuse.
"""

from __future__ import annotations

from typing import Any

import httpx
import streamlit as st

DEFAULT_TIMEOUT = 60


def _base_url() -> str:
    return str(st.secrets["API_URL"]).rstrip("/")


def _auth_headers() -> dict[str, str]:
    """Optional bearer token; the admin endpoints accept it when set."""
    token = st.secrets.get("API_ADMIN_TOKEN")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST helper — raises on non-2xx with the upstream body in the message."""
    url = f"{_base_url()}{path}"
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers=_auth_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"API call failed ({exc.response.status_code}): "
            f"{exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"API call failed: {exc}") from exc
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


# --------------------------------------------------------------------------- #
# Actions                                                                      #
# --------------------------------------------------------------------------- #


def send_reminder(
    volunteer_ids: list[str] | None = None,
    *,
    only_non_reporters: bool = False,
    message: str | None = None,
) -> dict[str, Any]:
    """Send a reminder to volunteers.

    * ``message`` set → send that free-text reminder (challenge nudge / custom),
      decoupled from kg progress. ``only_non_reporters`` is ignored.
    * ``message`` omitted → legacy kg progress reminder (filtered by
      ``only_non_reporters`` when set).
    * ``volunteer_ids`` empty / None → all active volunteers; provided → exact set.
    """
    return _post(
        "/admin/reminders/send",
        {
            "volunteer_ids": list(volunteer_ids or []),
            "only_non_reporters": bool(only_non_reporters),
            "message": (message or "").strip(),
        },
    )


def broadcast(message: str, channel: str | None = None) -> dict[str, Any]:
    """Broadcast a free-text announcement to every active volunteer.

    ``channel`` is forwarded as-is (``whatsapp`` / ``telegram`` / ``both``);
    omit to use the backend's active channel default.
    """
    return _post(
        "/admin/broadcast",
        {
            "message": message,
            "channel": channel,
        },
    )


def send_mission_brief(mission_id: str) -> dict[str, Any]:
    """Trigger ``SendMissionEducationBrief`` for ``mission_id``."""
    return _post(
        f"/admin/missions/{mission_id}/brief",
        {},
    )


def send_welcome_template(volunteer_id: str) -> dict[str, Any]:
    """Send the approved WhatsApp welcome template to a newly-added volunteer.

    Works cold (volunteer need not have messaged the bot). Requires the
    template approved in Meta + (dev mode) the number whitelisted.
    """
    return _post(f"/admin/volunteers/{volunteer_id}/welcome", {})


def recalculate_rankings() -> dict[str, Any]:
    """Trigger ``RankingCalculator.update_all_rankings()`` on the backend."""
    return _post("/admin/rankings/recalculate", {})


def election_action(team: str, action: str) -> dict[str, Any]:
    """Drive an election phase (same backend functions as the WA commands).

    ``action`` ∈ open_nomination, close_nomination, open_voting, close_voting,
    finalize, announce. Returns ``{ok, message}``.
    """
    return _post("/admin/elections/action", {"team": team, "action": action})


def generate_content(
    *, topic: str, tone: str, audience: str
) -> dict[str, Any]:
    """Returns ``{content: str}`` — short edu content ready to broadcast."""
    return _post(
        "/admin/content/generate",
        {"topic": topic, "tone": tone, "audience": audience},
    )


def generate_quiz(*, difficulty: str, num_options: int = 4) -> dict[str, Any]:
    """Returns ``{question, options, answer, explanation}``."""
    return _post(
        "/admin/quiz/generate",
        {"difficulty": difficulty, "num_options": num_options},
    )


def schedule_message(
    *,
    content: str | None = None,
    quiz: dict[str, Any] | None = None,
    recipient_filter: str = "all",
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    """Send (or schedule) a content / quiz blast.

    ``scheduled_at`` is an ISO-8601 string; omit for immediate send.
    """
    return _post(
        "/admin/messages/schedule",
        {
            "content": content,
            "quiz": quiz,
            "recipient_filter": recipient_filter,
            "scheduled_at": scheduled_at,
        },
    )


def generate_impact_report(
    *, target_kg: float | None = None
) -> dict[str, Any]:
    """Returns ``{total_kg, bottles, co2_kg, narrative}``."""
    return _post(
        "/admin/impact/generate",
        {"target_kg": target_kg},
    )


def preview_persona_response(
    *, test_name: str, settings: dict[str, Any]
) -> dict[str, Any]:
    """Render a sample agent reply using the supplied persona settings.

    Returns ``{response, greeting}``.
    """
    return _post(
        "/admin/persona/preview",
        {"test_name": test_name, "settings": settings},
    )
