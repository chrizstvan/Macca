"""Mission briefing agent that provides volunteers with task context and objectives."""

from typing import Any

from .base_agent import BaseAgent


class MissionBriefingAgent(BaseAgent):
    """Generates clear mission briefings for volunteers.

    Takes a mission description and optional metadata (location, deadline,
    required skills) from context and produces a structured briefing message
    ready to be sent to a volunteer via Telegram.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Mission Briefing officer for Macca, a volunteer coordination platform. "
            "Your job is to craft clear, motivating, and actionable mission briefings for volunteers. "
            "Always include: objective, location, timeline, required skills, and expected impact. "
            "Keep the tone friendly, professional, and encouraging. "
            "Format output as a structured message suitable for Telegram (use bold and emoji sparingly)."
        )

    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate a mission briefing from the provided mission description."""
        ctx = context or {}
        extra = ""
        if ctx:
            extra = f"Additional context: {ctx}"

        briefing = self._call_claude(message, extra_system=extra)
        return {
            "agent": "mission_briefing",
            "briefing": briefing,
            "mission_id": ctx.get("mission_id"),
        }
