"""Impact analyzer agent — narrative reports grounded in real numbers.

``process()`` dispatches by detected report type (weekly / monthly /
overall / by_area / by_volunteer), pulls the matching aggregation from
Supabase, and asks Sonnet for a narrative shaped to the detected output
format (sponsor / pemerintah / publik / default conversational).

``weekly_report()`` runs from the scheduler every Monday at 08:00 and
DMs the fasilitator a comprehensive weekly report via the channel-aware
notifier.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.agents.services.notifications import alert_fasilitator
from backend.database.supabase_client import db
from backend.utils.impact_calculator import ImpactCalculator

from .base_agent import BaseAgent, COMPLEX_MODEL
from .intent_registry import register_intent
from .prompts.impact_analyzer import (
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_REPORT_TYPE,
    OUTPUT_FORMAT_GUIDANCE,
    REPORT_TYPE_GUIDANCE,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

REPORT_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("weekly", ("minggu", "weekly", "7 hari", "seminggu")),
    ("monthly", ("bulan", "monthly", "30 hari", "sebulan")),
    ("by_area", ("per area", "per wilayah", "tiap area", "tiap wilayah")),
    (
        "by_volunteer",
        (
            "per volunteer",
            "siapa terbaik",
            "siapa volunteer",
            "volunteer terbaik",
            "ranking volunteer",
            "top volunteer",
        ),
    ),
    ("overall", ("total", "keseluruhan", "sejauh ini", "semua")),
)

OUTPUT_FORMAT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sponsor", ("sponsor", "donor", "investor")),
    ("pemerintah", ("pemerintah", "resmi", "official", "dinas", "kementerian")),
    ("publik", ("publik", "warga", "masyarakat", "sosmed", "publish")),
)

MILESTONE_THRESHOLDS_KG: tuple[int, ...] = (100, 250, 500, 1000, 2500, 5000)


# --------------------------------------------------------------------------- #
# Agent                                                                        #
# --------------------------------------------------------------------------- #


@register_intent(
    name="impact_analyzer",
    description=(
        "pertanyaan tentang dampak total program, statistik keseluruhan, "
        "laporan untuk sponsor/donor/pemerintah, rekap mingguan/bulanan, "
        "ranking per area atau per volunteer"
    ),
    examples=(
        "total program berapa kg sejauh ini?",
        "sudah berapa total yang terkumpul?",
        "berapa volunteer aktif sekarang?",
        "buat ringkasan dampak program buat sponsor",
        "rekap statistik mingguan buat laporan donor",
        "bandingkan area mana yang paling banyak",
        "siapa volunteer terbaik bulan ini?",
        "buat laporan resmi untuk pemerintah",
    ),
)
class ImpactAnalyzerAgent(BaseAgent):
    """Generates narrative impact reports keyed to report type + audience."""

    def __init__(self) -> None:
        super().__init__(
            name="impact_analyzer",
            description="Narrative impact reports for stakeholders",
        )

    # ------------------------------------------------------------------ #
    # Main entry                                                          #
    # ------------------------------------------------------------------ #

    async def process(self, message: str, context: dict) -> str:
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        report_type = self._detect_report_type(message)
        output_format = self._detect_output_format(message)
        data = self._aggregate(report_type)

        system_prompt = self._build_system_prompt(
            report_type=report_type,
            output_format=output_format,
            data=data,
        )

        history = (
            await self.get_chat_history(telegram_id) if telegram_id else []
        )
        messages = history + [{"role": "user", "content": message}]
        reply = await self.call_claude(
            system_prompt, messages, model=COMPLEX_MODEL, max_tokens=2200
        )

        if telegram_id:
            await self.save_chat_history(
                telegram_id, "user", message, self.name
            )
            await self.save_chat_history(
                telegram_id, "assistant", reply, self.name
            )
        return reply

    # ------------------------------------------------------------------ #
    # Scheduled weekly report                                             #
    # ------------------------------------------------------------------ #

    async def weekly_report(self) -> str:
        """Generate the Monday 08:00 weekly report and DM the fasilitator."""
        data = self._aggregate("weekly")
        system_prompt = self._build_system_prompt(
            report_type="weekly", output_format="default", data=data
        )
        report = await self.call_claude(
            system_prompt,
            [
                {
                    "role": "user",
                    "content": (
                        "Buat laporan mingguan program minggu ini, "
                        "lengkap dengan metrik kunci dan trend."
                    ),
                }
            ],
            model=COMPLEX_MODEL,
            max_tokens=2200,
        )
        await alert_fasilitator(
            "📊 Laporan mingguan program siap:\n\n" + report
        )
        return report

    # ------------------------------------------------------------------ #
    # Detection                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_report_type(message: str) -> str:
        lowered = (message or "").lower()
        for canonical, triggers in REPORT_TYPE_KEYWORDS:
            if any(t in lowered for t in triggers):
                return canonical
        return DEFAULT_REPORT_TYPE

    @staticmethod
    def _detect_output_format(message: str) -> str:
        lowered = (message or "").lower()
        for canonical, triggers in OUTPUT_FORMAT_KEYWORDS:
            if any(t in lowered for t in triggers):
                return canonical
        return DEFAULT_OUTPUT_FORMAT

    # ------------------------------------------------------------------ #
    # Prompt assembly                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_system_prompt(
        *,
        report_type: str,
        output_format: str,
        data: dict[str, Any],
    ) -> str:
        report_guidance = REPORT_TYPE_GUIDANCE.get(
            report_type, REPORT_TYPE_GUIDANCE[DEFAULT_REPORT_TYPE]
        )
        format_guidance = OUTPUT_FORMAT_GUIDANCE.get(
            output_format, OUTPUT_FORMAT_GUIDANCE[DEFAULT_OUTPUT_FORMAT]
        )

        data_block = ImpactAnalyzerAgent._format_data_block(data)
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"{report_guidance}\n\n"
            f"{format_guidance}\n\n"
            f"{data_block}"
        )

    @staticmethod
    def _format_data_block(data: dict[str, Any]) -> str:
        impact = ImpactCalculator.format_impact_summary(data["period_kg"])
        narrative = ImpactCalculator.format_impact_narrative(data["period_kg"])

        per_area_lines = [
            f"  - {area}: {kg:g} kg" for area, kg in data["per_area"][:8]
        ] or ["  - (belum ada data area)"]
        top_lines = [
            f"  - {name}: {kg:g} kg" for name, kg in data["top_volunteers"]
        ] or ["  - (belum ada volunteer aktif)"]
        bottom_lines = [
            f"  - {name}: {kg:g} kg" for name, kg in data["bottom_volunteers"]
        ] or ["  - (tidak ada data)"]
        non_reporters = (
            ", ".join(data["non_reporters"][:10])
            if data["non_reporters"]
            else "tidak ada (semua volunteer sudah lapor)"
        )
        milestone_text = (
            ", ".join(f"{m} kg" for m in data["milestones"])
            if data["milestones"]
            else "tidak ada milestone baru di periode ini"
        )

        return (
            "=== DATA PROGRAM ===\n"
            f"Periode: {data['period_label']}\n"
            f"Total kg di periode ini: {data['period_kg']:g} kg\n"
            f"Total kg program (sejak awal): {data['program_kg']:g} kg\n"
            f"Volunteer aktif lapor (periode): {data['active_volunteers']} orang\n"
            f"Volunteer terdaftar aktif (program): {data['total_active_volunteers']} orang\n"
            f"Volunteer belum lapor (periode): {non_reporters}\n"
            f"Trend vs periode sebelumnya: {data['trend_text']}\n"
            f"Milestone tercapai di periode: {milestone_text}\n"
            "Top areas (kg):\n"
            + "\n".join(per_area_lines)
            + "\nTop volunteers:\n"
            + "\n".join(top_lines)
            + "\nBottom volunteers (perlu perhatian):\n"
            + "\n".join(bottom_lines)
            + "\n\n"
            "Dampak periode (gunakan angka ini di narasi):\n"
            f"- Botol diselamatkan: {impact['bottles']:,}\n"
            f"- CO₂ dicegah: {impact['co2_kg']:g} kg\n"
            f"- Air dihemat: {impact['water_liters']:g} liter\n"
            f"- Narasi referensi: {narrative}"
        )

    # ------------------------------------------------------------------ #
    # Aggregation                                                         #
    # ------------------------------------------------------------------ #

    def _aggregate(self, report_type: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        period_start, period_end, prev_start, prev_end, period_label = (
            self._period_bounds(report_type, now)
        )

        period_rows = self._fetch_reports(period_start, period_end)
        prev_rows = (
            self._fetch_reports(prev_start, prev_end)
            if prev_start is not None
            else []
        )

        program_kg = self._sum_reports_before(now.isoformat())
        period_kg = sum(float(r.get("kg_collected") or 0) for r in period_rows)
        prev_kg = sum(float(r.get("kg_collected") or 0) for r in prev_rows)

        # Volunteer aggregation (period)
        kg_by_volunteer: dict[str, float] = defaultdict(float)
        for row in period_rows:
            kg_by_volunteer[row["volunteer_id"]] += float(
                row.get("kg_collected") or 0
            )
        per_area_map: dict[str, float] = defaultdict(float)
        for row in period_rows:
            loc = (row.get("location") or "unknown").strip() or "unknown"
            per_area_map[loc] += float(row.get("kg_collected") or 0)
        per_area = sorted(per_area_map.items(), key=lambda kv: kv[1], reverse=True)

        names_by_id = self._fetch_volunteer_names(list(kg_by_volunteer))
        ranked = sorted(
            ((names_by_id.get(vid, "?"), kg) for vid, kg in kg_by_volunteer.items()),
            key=lambda kv: kv[1],
            reverse=True,
        )
        top_volunteers = ranked[:5]
        bottom_volunteers = list(reversed(ranked[-3:])) if len(ranked) > 3 else []

        active_volunteers = self._fetch_active_volunteers()
        total_active_volunteers = len(active_volunteers)
        reporters_ids = set(kg_by_volunteer.keys())
        non_reporters = [
            v["name"]
            for v in active_volunteers
            if v["id"] not in reporters_ids
        ]

        # Milestones crossed during period (using program totals)
        program_before_period = self._sum_reports_before(period_start.isoformat())
        program_at_period_end = program_before_period + period_kg
        milestones = [
            t
            for t in MILESTONE_THRESHOLDS_KG
            if program_before_period < t <= program_at_period_end
        ]

        trend_text = self._format_trend(period_kg, prev_kg)

        return {
            "period_label": period_label,
            "period_kg": round(period_kg, 2),
            "program_kg": round(program_kg, 2),
            "active_volunteers": len(reporters_ids),
            "total_active_volunteers": total_active_volunteers,
            "non_reporters": non_reporters,
            "per_area": [(a, round(k, 2)) for a, k in per_area],
            "top_volunteers": [(n, round(k, 2)) for n, k in top_volunteers],
            "bottom_volunteers": [
                (n, round(k, 2)) for n, k in bottom_volunteers
            ],
            "milestones": milestones,
            "trend_text": trend_text,
        }

    @staticmethod
    def _period_bounds(
        report_type: str, now: datetime
    ) -> tuple[datetime, datetime, datetime | None, datetime | None, str]:
        if report_type == "weekly":
            start = (now - timedelta(days=7)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            prev_start = start - timedelta(days=7)
            return (
                start,
                now,
                prev_start,
                start,
                f"{start.date()} → {now.date()} (7 hari terakhir)",
            )
        if report_type == "monthly":
            start = (now - timedelta(days=30)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            prev_start = start - timedelta(days=30)
            return (
                start,
                now,
                prev_start,
                start,
                f"{start.date()} → {now.date()} (30 hari terakhir)",
            )
        # by_area / by_volunteer / overall — full program history
        # (with rolling 30-day comparison for trend on overall paths).
        epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
        prev_start = (now - timedelta(days=60)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        prev_end = (now - timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return epoch, now, prev_start, prev_end, "keseluruhan program"

    @staticmethod
    def _fetch_reports(start: datetime, end: datetime) -> list[dict]:
        return (
            db.table("reports")
            .select("volunteer_id, kg_collected, location, reported_at")
            .gte("reported_at", start.isoformat())
            .lt("reported_at", end.isoformat())
            .execute()
            .data
            or []
        )

    @staticmethod
    def _sum_reports_before(timestamp_iso: str) -> float:
        rows = (
            db.table("reports")
            .select("kg_collected")
            .lt("reported_at", timestamp_iso)
            .execute()
            .data
            or []
        )
        return sum(float(r.get("kg_collected") or 0) for r in rows)

    @staticmethod
    def _fetch_volunteer_names(ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        rows = (
            db.table("volunteers")
            .select("id, name")
            .in_("id", ids)
            .execute()
            .data
            or []
        )
        return {r["id"]: r.get("name") or "?" for r in rows}

    @staticmethod
    def _fetch_active_volunteers() -> list[dict]:
        rows = (
            db.table("volunteers")
            .select("id, name")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        return rows

    @staticmethod
    def _format_trend(current_kg: float, prev_kg: float) -> str:
        if prev_kg == 0:
            return f"baseline (periode sebelumnya 0 kg, sekarang {current_kg:g} kg)"
        diff = current_kg - prev_kg
        pct = (diff / prev_kg) * 100
        direction = "naik" if diff >= 0 else "turun"
        return (
            f"{direction} {abs(pct):.0f}% "
            f"({prev_kg:g} kg → {current_kg:g} kg)"
        )
