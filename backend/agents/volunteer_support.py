"""Volunteer support agent that answers questions and provides guidance."""

from typing import Any

from .base_agent import BaseAgent


class VolunteerSupportAgent(BaseAgent):
    """General-purpose support agent for volunteers.

    Handles FAQs, onboarding questions, logistical queries, and anything
    that doesn't fit a more specialised agent. Falls back gracefully and
    can escalate to a human fasilitator when needed.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are a friendly volunteer support assistant for Macca, a volunteer coordination platform. "
            "Help volunteers with questions about their missions, the platform, logistics, and general guidance. "
            "Be warm, clear, and concise. If a question requires human intervention, say so explicitly "
            "and indicate that a fasilitator will follow up. Format responses for Telegram."
        )

    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Respond to a volunteer support query."""
        ctx = context or {}
        extra = f"Volunteer ID: {ctx.get('volunteer_id', 'unknown')}." if ctx else ""

        response = self._call_claude(message, extra_system=extra)
        needs_human = any(
            kw in response.lower()
            for kw in ("fasilitator will follow up", "human intervention", "escalate")
        )
        return {
            "agent": "volunteer_support",
            "response": response,
            "needs_human_followup": needs_human,
            "volunteer_id": ctx.get("volunteer_id"),
        }
