"""On-demand draft mixin: checklist, impact report, education — DRAFT ONLY.

Triggered when the fasilitator asks to build content manually
("buatkan checklist challenge X", "bikin laporan impact minggu ini",
"buatkan edukasi mikroplastik"). Every handler returns copy-paste-ready text
ending with the same group hand-off line; nothing is sent to volunteers and
there is no approval/scheduling step.
"""

from __future__ import annotations

import logging
import re

from ..base_agent import COMPLEX_MODEL

logger = logging.getLogger(__name__)

# CO₂ absorbed by one tree in a month (~21.7 kg/year ÷ 12).
_CO2_KG_PER_TREE_MONTH = 1.81

_COPY_PASTE_TAIL = "\n\nTinggal copy-paste ke grup WA ya!"

_CHECKLIST_PATTERN = re.compile(
    r"\b(?:buatkan|bikin|buat)\s+checklist\b", re.IGNORECASE
)
_IMPACT_PATTERN = re.compile(
    r"\b(?:buatkan|bikin|buat)\s+(?:laporan|report)\s+(?:impact|dampak)\b",
    re.IGNORECASE,
)
_EDUCATION_PATTERN = re.compile(
    r"\b(?:buatkan|bikin|buat)\s+edukasi\b", re.IGNORECASE
)


class OnDemandDraftMixin:
    """Manual, draft-only generation of checklist / impact / education text."""

    # ------------------------------------------------------------------ #
    # Detection + dispatch                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _ondemand_draft_kind(message: str) -> str | None:
        """Return 'checklist' | 'impact' | 'education', or None."""
        if not message:
            return None
        if _CHECKLIST_PATTERN.search(message):
            return "checklist"
        if _IMPACT_PATTERN.search(message):
            return "impact"
        if _EDUCATION_PATTERN.search(message):
            return "education"
        return None

    async def _handle_ondemand_draft(self, message: str, context: dict) -> str:
        kind = self._ondemand_draft_kind(message)
        if kind == "checklist":
            return await self._handle_checklist_draft(message)
        if kind == "impact":
            return await self._handle_impact_draft(message)
        if kind == "education":
            return await self._handle_education_ondemand(message)
        return ""  # unreachable — caller gates on _ondemand_draft_kind

    # ------------------------------------------------------------------ #
    # Checklist                                                           #
    # ------------------------------------------------------------------ #

    async def _handle_checklist_draft(self, message: str) -> str:
        from backend.database.supabase_client import db
        from backend.utils.action_item_resolver import ActionItemResolver

        match = _CHECKLIST_PATTERN.search(message)
        rest = message[match.end():].strip()
        challenge_name = re.sub(
            r"^(?:untuk\s+)?(?:challenge\s+)?", "", rest, flags=re.IGNORECASE
        ).strip()
        if not challenge_name:
            return "Sebutkan challenge-nya, contoh: `buatkan checklist challenge bersih pantai`."

        resolver = ActionItemResolver(db, llm_caller=self.call_claude)
        try:
            item = await resolver.find_by_mention(challenge_name, "challenge")
        except Exception as exc:
            logger.warning("checklist challenge lookup failed: %s", exc)
            return "Gagal mencari challenge (apakah tabel `action_items` sudah ada?)."

        if item is None:
            return f"Challenge '{challenge_name}' belum ada di dashboard."
        if isinstance(item, list):
            titles = "\n".join(f"• {a.get('title', '?')}" for a in item[:8])
            return (
                f"Ada beberapa challenge cocok '{challenge_name}':\n{titles}\n\n"
                "Sebutkan judul lengkapnya ya."
            )

        system_prompt = (
            "Buat checklist sederhana (5-7 item) untuk challenge ini, format "
            "siap dibagikan di grup WA. Pakai checkbox emoji.\n"
            f"Challenge: {item.get('title', '')}\n"
            f"Deskripsi: {item.get('description', '')}"
        )
        checklist = await self.call_claude(
            system_prompt,
            [{"role": "user", "content": "Buat checklist."}],
            model=COMPLEX_MODEL,
        )
        return (
            f"📋 DRAFT Checklist: {item.get('title', '')}\n\n"
            f"{checklist.strip()}"
            + _COPY_PASTE_TAIL
        )

    # ------------------------------------------------------------------ #
    # Impact report                                                       #
    # ------------------------------------------------------------------ #

    async def _handle_impact_draft(self, message: str) -> str:
        from backend.agents.impact_analyzer import ImpactAnalyzerAgent
        from backend.utils.impact_calculator import ImpactCalculator

        period = "minggu ini" if "minggu" in message.lower() else (
            "bulan ini" if "bulan" in message.lower() else "minggu ini"
        )
        try:
            stats = await ImpactAnalyzerAgent().impact_stats(message)
        except Exception as exc:
            logger.warning("impact stats failed: %s", exc)
            return "Gagal mengambil data dampak. Coba lagi sebentar."

        total_kg = float(stats.get("period_kg") or 0)
        bottles = ImpactCalculator.kg_to_bottles(total_kg)
        co2_kg = ImpactCalculator.kg_to_co2_prevented(total_kg)
        trees = round(co2_kg / _CO2_KG_PER_TREE_MONTH) if co2_kg else 0
        top = stats.get("top_volunteers") or []
        top_contributor = top[0][0] if top else "-"

        return (
            f"📊 Laporan Dampak — {period}\n\n"
            f"♻️ Total plastik terkumpul: {total_kg:g} kg\n"
            f"🍶 {bottles:,} botol plastik diselamatkan\n"
            f"🌍 {round(co2_kg)} kg emisi CO₂ dicegah\n"
            f"🌳 Setara {trees} pohon menyerap karbon sebulan\n\n"
            f"🙌 {stats.get('active_volunteers', 0)} volunteer aktif berkontribusi\n"
            f"🏆 Top kontributor: {top_contributor}\n\n"
            "Terima kasih semua! Kita membuat perbedaan nyata 💚"
            + _COPY_PASTE_TAIL
        )

    # ------------------------------------------------------------------ #
    # Education (manual trigger of the C.2 generator)                     #
    # ------------------------------------------------------------------ #

    async def _handle_education_ondemand(self, message: str) -> str:
        from backend.agents.education_generator import EducationContentGenerator

        match = _EDUCATION_PATTERN.search(message)
        rest = message[match.end():].strip()
        topic = re.sub(
            r"^(?:tentang\s+|soal\s+)?", "", rest, flags=re.IGNORECASE
        ).strip()

        generator = EducationContentGenerator()
        if not topic:
            topic = generator.topic_for(generator.rotation_index())

        content = await generator.generate(topic)
        # build_draft_message already ends with the copy-paste hand-off.
        return generator.build_draft_message(topic, content)
