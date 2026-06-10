"""Fasilitator hub agent that provides tools and summaries for mission facilitators."""

from typing import Any

from .base_agent import BaseAgent


class FasilitatorHubAgent(BaseAgent):
    """Dedicated agent for fasilitator-facing operations.

    Fasilitators coordinate volunteers and missions. This agent generates
    operational summaries, escalation digests, volunteer roster insights,
    and recommended actions to help fasilitators manage their teams
    efficiently from the Telegram interface.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Fasilitator Hub assistant for Macca, a volunteer coordination platform. "
            "You assist mission fasilitators — the people who coordinate volunteers on the ground. "
            "Provide concise operational summaries, highlight escalations that need attention, "
            "suggest resource reallocation when volunteers are stuck, and help fasilitators "
            "communicate clearly with their teams. "
            "Tone: efficient, clear, and action-oriented. Format for Telegram."
        )

    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process a fasilitator request and return an operational response."""
        ctx = context or {}
        extra = (
            f"Fasilitator ID: {ctx.get('fasilitator_id', 'unknown')}. "
            f"Active missions: {ctx.get('active_missions', [])}. "
            f"Pending escalations: {ctx.get('pending_escalations', 0)}."
        )

        response = self._call_claude(message, extra_system=extra)
        return {
            "agent": "fasilitator_hub",
            "response": response,
            "fasilitator_id": ctx.get("fasilitator_id"),
            "active_missions": ctx.get("active_missions", []),
        }
