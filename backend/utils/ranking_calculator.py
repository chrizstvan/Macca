"""Score + rank computation for the volunteer leaderboard.

Weights (per spec):
    total_score = impact_score * 0.95 + quiz_score * 0.05

Both component scores are clamped to ``0..MAX_COMPONENT_SCORE`` so the
weighted total is bounded.

This module is intentionally lightweight: it talks only to Supabase via
the shared ``db`` client and does no I/O of its own. All public methods
are ``async`` for ergonomics, even though the underlying Postgrest calls
are synchronous — that keeps callers consistent with the rest of the
agent codebase.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from backend.database.supabase_client import db
from backend.utils.date_utils import parse_iso_date
from backend.utils.query_utils import get_active_mission as _shared_get_active_mission

logger = logging.getLogger(__name__)

MAX_COMPONENT_SCORE = 100.0
IMPACT_WEIGHT = 0.95
QUIZ_WEIGHT = 0.05

BONUS_CONSISTENT_REPORTING = 10  # ≥ MIN_REPORT_DAYS distinct reporting days
BONUS_EARLY_COMPLETION = 5       # met quota before the mission deadline
BONUS_PER_QUALITY_REPORT = 2     # verified=True AND photo_url present

MIN_REPORT_DAYS_FOR_BONUS = 5

POINTS_PER_CORRECT_ANSWER = 10


def _clamp(value: float, hi: float = MAX_COMPONENT_SCORE) -> float:
    return max(0.0, min(value, hi))


class RankingCalculator:
    """Compute, persist, and read back per-volunteer scores + ranks."""

    # ------------------------------------------------------------------ #
    # Component scoring                                                   #
    # ------------------------------------------------------------------ #

    async def calculate_impact_score(self, volunteer_id: str) -> float:
        """Score derived from collection performance vs assigned quota.

        Base       = total_kg / quota_kg * 100  (capped at 100)
        Bonuses    = consistency, early completion, quality reports
        Final      = clamp(base + bonuses, 0, 100)
        """
        mission, assignment = _shared_get_active_mission(
            volunteer_id, with_assignment=True
        )
        if mission is None or assignment is None:
            return 0.0

        quota = float(assignment.get("quota_kg") or 0)
        if quota <= 0:
            return 0.0

        reports = (
            db.table("reports")
            .select("kg_collected, reported_at, verified, photo_url")
            .eq("volunteer_id", volunteer_id)
            .eq("mission_id", mission.get("id"))
            .execute()
            .data
            or []
        )

        total_kg = sum(float(r.get("kg_collected") or 0) for r in reports)
        base = (total_kg / quota) * 100 if quota else 0

        distinct_days = {
            parse_iso_date(r.get("reported_at"))
            for r in reports
            if parse_iso_date(r.get("reported_at")) is not None
        }
        consistency_bonus = (
            BONUS_CONSISTENT_REPORTING
            if len(distinct_days) >= MIN_REPORT_DAYS_FOR_BONUS
            else 0
        )

        early_bonus = 0
        deadline = parse_iso_date(mission.get("deadline"))
        if total_kg >= quota and deadline is not None and deadline >= date.today():
            early_bonus = BONUS_EARLY_COMPLETION

        quality_reports = sum(
            1 for r in reports if r.get("verified") and r.get("photo_url")
        )
        quality_bonus = quality_reports * BONUS_PER_QUALITY_REPORT

        score = _clamp(base) + consistency_bonus + early_bonus + quality_bonus
        return round(_clamp(score), 2)

    async def calculate_quiz_score(self, volunteer_id: str) -> float:
        """Score derived from quiz attempts: ratio × 100, capped at 100."""
        rows = (
            db.table("quiz_attempts")
            .select("is_correct")
            .eq("volunteer_id", volunteer_id)
            .execute()
            .data
            or []
        )
        if not rows:
            return 0.0

        correct = sum(1 for r in rows if r.get("is_correct"))
        ratio = correct / len(rows)
        ratio_score = ratio * 100
        # Each correct answer also accrues 10 points (still clamped at 100).
        point_score = correct * POINTS_PER_CORRECT_ANSWER
        return round(_clamp(max(ratio_score, point_score)), 2)

    # ------------------------------------------------------------------ #
    # Persistence                                                         #
    # ------------------------------------------------------------------ #

    async def upsert_score(
        self, volunteer_id: str, impact_score: float, quiz_score: float
    ) -> None:
        """Upsert ``volunteer_scores`` for a single volunteer; ranks come later."""
        payload = {
            "volunteer_id": volunteer_id,
            "impact_score": impact_score,
            "quiz_score": quiz_score,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        try:
            db.table("volunteer_scores").upsert(
                payload, on_conflict="volunteer_id"
            ).execute()
        except Exception as exc:
            logger.error("Failed to upsert volunteer_scores for %s: %s", volunteer_id, exc)

    async def refresh_volunteer(self, volunteer_id: str) -> None:
        """Recompute both component scores and upsert."""
        impact = await self.calculate_impact_score(volunteer_id)
        quiz = await self.calculate_quiz_score(volunteer_id)
        await self.upsert_score(volunteer_id, impact, quiz)

    # ------------------------------------------------------------------ #
    # Ranking                                                             #
    # ------------------------------------------------------------------ #

    async def update_all_rankings(self) -> int:
        """Refresh scores for every volunteer, then assign ranks.

        Returns the number of volunteers ranked.
        """
        volunteers = (
            db.table("volunteers").select("id").execute().data or []
        )
        for v in volunteers:
            await self.refresh_volunteer(v["id"])

        rows = (
            db.table("volunteer_scores")
            .select("volunteer_id, total_score, rank")
            .execute()
            .data
            or []
        )
        rows.sort(key=lambda r: float(r.get("total_score") or 0), reverse=True)

        for new_rank, row in enumerate(rows, start=1):
            prev = row.get("rank")
            try:
                db.table("volunteer_scores").update(
                    {"prev_rank": prev, "rank": new_rank}
                ).eq("volunteer_id", row["volunteer_id"]).execute()
            except Exception as exc:
                logger.error(
                    "Rank write failed for %s: %s", row["volunteer_id"], exc
                )
        logger.info("Ranked %d volunteers", len(rows))
        return len(rows)

    async def get_leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        """Top-N volunteers with the info the chat + dashboard need."""
        scores = (
            db.table("volunteer_scores")
            .select(
                "volunteer_id, impact_score, quiz_score, total_score, "
                "rank, prev_rank"
            )
            .order("rank", desc=False)
            .limit(limit)
            .execute()
            .data
            or []
        )
        if not scores:
            return []

        ids = [s["volunteer_id"] for s in scores]
        volunteers = {
            v["id"]: v
            for v in (
                db.table("volunteers")
                .select("id, name, area")
                .in_("id", ids)
                .execute()
                .data
                or []
            )
        }

        # Total kg per volunteer (across any mission) for the leaderboard line
        reports = (
            db.table("reports")
            .select("volunteer_id, kg_collected")
            .in_("volunteer_id", ids)
            .execute()
            .data
            or []
        )
        kg_by_volunteer: dict[str, float] = defaultdict(float)
        for r in reports:
            kg_by_volunteer[r["volunteer_id"]] += float(r.get("kg_collected") or 0)

        # Quiz correct counts
        quiz_rows = (
            db.table("quiz_attempts")
            .select("volunteer_id, is_correct")
            .in_("volunteer_id", ids)
            .execute()
            .data
            or []
        )
        correct_by_volunteer: dict[str, int] = defaultdict(int)
        for q in quiz_rows:
            if q.get("is_correct"):
                correct_by_volunteer[q["volunteer_id"]] += 1

        out: list[dict[str, Any]] = []
        for s in scores:
            vid = s["volunteer_id"]
            v = volunteers.get(vid, {})
            prev = s.get("prev_rank")
            rank = s.get("rank")
            rank_change = (prev - rank) if (prev is not None and rank is not None) else 0
            out.append(
                {
                    "volunteer_id": vid,
                    "name": v.get("name") or "(tanpa nama)",
                    "area": v.get("area") or "-",
                    "rank": rank,
                    "prev_rank": prev,
                    "rank_change": rank_change,
                    "impact_score": float(s.get("impact_score") or 0),
                    "quiz_score": float(s.get("quiz_score") or 0),
                    "total_score": float(s.get("total_score") or 0),
                    "kg_collected": round(kg_by_volunteer.get(vid, 0), 2),
                    "quiz_correct_count": correct_by_volunteer.get(vid, 0),
                }
            )
        return out

    async def get_personal_rank(self, volunteer_id: str) -> dict[str, Any] | None:
        """Single volunteer's rank entry + the person just above them, if any."""
        own = (
            db.table("volunteer_scores")
            .select("volunteer_id, rank, total_score, impact_score, quiz_score")
            .eq("volunteer_id", volunteer_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not own:
            return None
        row = own[0]
        own_rank = row.get("rank")

        total_count = (
            db.table("volunteer_scores")
            .select("id", count="exact")
            .execute()
            .count
            or 0
        )

        ahead_name: str | None = None
        if own_rank and own_rank > 1:
            ahead = (
                db.table("volunteer_scores")
                .select("volunteer_id")
                .eq("rank", own_rank - 1)
                .limit(1)
                .execute()
                .data
                or []
            )
            if ahead:
                ahead_volunteer = (
                    db.table("volunteers")
                    .select("name")
                    .eq("id", ahead[0]["volunteer_id"])
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if ahead_volunteer:
                    ahead_name = ahead_volunteer[0].get("name")

        kg_total = sum(
            float(r.get("kg_collected") or 0)
            for r in (
                db.table("reports")
                .select("kg_collected")
                .eq("volunteer_id", volunteer_id)
                .execute()
                .data
                or []
            )
        )

        quiz_correct = sum(
            1
            for q in (
                db.table("quiz_attempts")
                .select("is_correct")
                .eq("volunteer_id", volunteer_id)
                .execute()
                .data
                or []
            )
            if q.get("is_correct")
        )

        return {
            "rank": own_rank,
            "total_count": total_count,
            "total_score": float(row.get("total_score") or 0),
            "impact_score": float(row.get("impact_score") or 0),
            "quiz_score": float(row.get("quiz_score") or 0),
            "kg_collected": round(kg_total, 2),
            "quiz_correct_count": quiz_correct,
            "ahead_name": ahead_name,
        }

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    _parse_iso_date = staticmethod(parse_iso_date)
