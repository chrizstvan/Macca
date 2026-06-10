"""Progress tracker agent that monitors and reports volunteer mission progress."""

from typing import Any

from .base_agent import BaseAgent


class ProgressTrackerAgent(BaseAgent):
    """Tracks volunteer progress and generates status updates.

    Accepts progress data from context (completed tasks, blockers, percentage)
    and produces human-readable summaries, escalation flags, and next-step
    recommendations for both volunteers and fasilitators.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Progress Tracker for Macca, a volunteer coordination platform. "
            "Analyse volunteer progress reports and provide structured feedback. "
            "Identify blockers, celebrate wins, suggest next steps, and flag anything "
            "that needs fasilitator attention. "
            "Be concise, data-driven, and supportive. Format for Telegram."
        )

    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Analyse a progress update and return structured feedback."""
        ctx = context or {}
        extra = ""
        if ctx:
            extra = (
                f"Mission ID: {ctx.get('mission_id', 'unknown')}. "
                f"Volunteer: {ctx.get('volunteer_name', 'unknown')}. "
                f"Completion: {ctx.get('completion_pct', 'unknown')}%."
            )

        analysis = self._call_claude(message, extra_system=extra)
        needs_escalation = any(
            kw in analysis.lower() for kw in ("blocker", "escalate", "urgent", "stuck")
        )
        return {
            "agent": "progress_tracker",
            "analysis": analysis,
            "needs_escalation": needs_escalation,
            "mission_id": ctx.get("mission_id"),
            "volunteer_id": ctx.get("volunteer_id"),
        }
