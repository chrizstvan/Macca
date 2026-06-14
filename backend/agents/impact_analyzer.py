"""Impact analyzer agent that quantifies and narrates mission outcomes."""

from .base_agent import BaseAgent, COMPLEX_MODEL
from .intent_registry import register_intent
from .prompts.impact_analyzer import SYSTEM_PROMPT
from backend.database.supabase_client import db


@register_intent(
    name="impact_analyzer",
    description=(
        "pertanyaan tentang dampak total program, statistik keseluruhan, "
        "laporan untuk sponsor/donor"
    ),
    examples=(
        "total program berapa kg sejauh ini?",
        "sudah berapa total yang terkumpul?",
        "berapa volunteer aktif sekarang?",
        "buat ringkasan dampak program buat sponsor",
        "rekap statistik mingguan buat laporan donor",
    ),
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
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)

        reports = (
            db.table("reports")
            .select("kg_collected, location, reported_at, verified, is_flagged")
            .order("reported_at", desc=True)
            .limit(100)
            .execute()
            .data
            or []
        )
        total = sum(float(r["kg_collected"]) for r in reports)
        extra = f"\n\nReport data ({len(reports)} reports, {total} kg total): {reports}"

        if context.get("persona") == "fasilitator":
            extra += self._fasilitator_breakdown(reports)

        telegram_id = context.get("telegram_id")
        messages = [{"role": "user", "content": message}]
        reply = await self.call_claude(
            SYSTEM_PROMPT + extra, messages, model=COMPLEX_MODEL, max_tokens=2000
        )
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply

    @staticmethod
    def _fasilitator_breakdown(reports: list[dict]) -> str:
        """Add verified/flagged counts + top-5 areas for the fasilitator persona."""
        verified = sum(1 for r in reports if r.get("verified"))
        flagged = sum(1 for r in reports if r.get("is_flagged"))
        by_area: dict[str, float] = {}
        for r in reports:
            location = (r.get("location") or "unknown")
            by_area[location] = by_area.get(location, 0) + float(r.get("kg_collected") or 0)
        top_areas = sorted(by_area.items(), key=lambda kv: kv[1], reverse=True)[:5]
        top_str = ", ".join(f"{a} ({kg:g} kg)" for a, kg in top_areas) or "-"
        return (
            "\n\nFasilitator breakdown:\n"
            f"- Verified: {verified}/{len(reports)}\n"
            f"- Flagged: {flagged}/{len(reports)}\n"
            f"- Top 5 areas: {top_str}"
        )
