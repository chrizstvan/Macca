"""Impact analyzer agent that quantifies and narrates mission outcomes."""

from .base_agent import BaseAgent, COMPLEX_MODEL
from backend.database.supabase_client import db

SYSTEM_PROMPT = (
    "You are the Impact Analyst for Macca, a volunteer coordination platform for waste "
    "collection missions. Analyse the collection data provided and produce clear, "
    "evidence-based impact assessments: total kg collected, top areas, volunteer "
    "participation, and trends. Quantify wherever possible and add a short narrative. "
    "Tone: professional and data-driven, but accessible. Format for Telegram."
)


class ImpactAnalyzerAgent(BaseAgent):
    """Aggregates report data and produces quantified impact summaries."""

    def __init__(self) -> None:
        super().__init__(
            name="impact_analyzer",
            description="Quantifies and narrates mission impact from report data",
        )

    async def process(self, message: str, context: dict) -> str:
        """Produce an impact analysis from verified collection reports."""
        reports = (
            db.table("reports")
            .select("kg_collected, location, reported_at, verified")
            .order("reported_at", desc=True)
            .limit(100)
            .execute()
            .data
            or []
        )
        total = sum(float(r["kg_collected"]) for r in reports)
        extra = f"\n\nReport data ({len(reports)} reports, {total} kg total): {reports}"

        telegram_id = context.get("telegram_id")
        messages = [{"role": "user", "content": message}]
        reply = await self.call_claude(
            SYSTEM_PROMPT + extra, messages, model=COMPLEX_MODEL, max_tokens=2000
        )
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply
