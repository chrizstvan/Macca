"""Impact analyzer agent that quantifies and narrates mission outcomes."""

from .base_agent import BaseAgent, COMPLEX_MODEL
from .prompts.impact_analyzer import SYSTEM_PROMPT
from backend.database.supabase_client import db


class ImpactAnalyzerAgent(BaseAgent):
    """Aggregates report data and produces quantified impact summaries."""

    def __init__(self) -> None:
        super().__init__(
            name="impact_analyzer",
            description="Quantifies and narrates mission impact from report data",
        )

    async def process(self, message: str, context: dict) -> str:
        """Produce an impact analysis from verified collection reports."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)

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
