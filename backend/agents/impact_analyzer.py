"""Impact analyzer agent that quantifies and narrates mission outcomes."""

from typing import Any

from .base_agent import BaseAgent
from backend.utils.impact_calculator import calculate_impact_score


class ImpactAnalyzerAgent(BaseAgent):
    """Analyses mission data to produce quantified impact assessments.

    Combines raw metrics from context with Claude's narrative reasoning to
    generate reports suitable for donors, stakeholders, and internal review.
    """

    @property
    def system_prompt(self) -> str:
        return (
            "You are the Impact Analyst for Macca, a volunteer coordination platform. "
            "Analyse mission data and produce clear, evidence-based impact assessments. "
            "Quantify outcomes where possible (people helped, hours volunteered, resources distributed). "
            "Provide a narrative summary, key metrics, and recommendations for improving future missions. "
            "Tone: professional and data-driven, but human and accessible."
        )

    async def handle(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Produce an impact analysis for a completed or in-progress mission."""
        ctx = context or {}
        metrics = ctx.get("metrics", {})
        impact_score = calculate_impact_score(metrics)

        extra = (
            f"Mission ID: {ctx.get('mission_id', 'unknown')}. "
            f"Raw metrics: {metrics}. "
            f"Calculated impact score: {impact_score}."
        )

        analysis = self._call_claude(message, extra_system=extra)
        return {
            "agent": "impact_analyzer",
            "analysis": analysis,
            "impact_score": impact_score,
            "metrics": metrics,
            "mission_id": ctx.get("mission_id"),
        }
