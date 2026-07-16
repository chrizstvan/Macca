"""Supabase access for the dashboard.

Read-only helpers. Each function returns a ``pandas.DataFrame`` so pages can
filter / sort / chart without re-implementing dict wrangling. Results are
cached for ``CACHE_TTL`` seconds — the dashboard is a snapshot view, not a
real-time console, so a 30-second TTL is fine and slashes Supabase round
trips.

Why a thin module instead of a class:
* All callers want the same Supabase client. ``@st.cache_resource``
  guarantees a single client per Streamlit session.
* Each ``get_*`` is a pure function over that client → easy to mock from
  tests / notebooks.
* DRY: shared "today_iso" + "days_since" helpers live here, not in each
  page.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import Client, create_client

CACHE_TTL = 30  # seconds
JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


# --------------------------------------------------------------------------- #
# Client                                                                       #
# --------------------------------------------------------------------------- #


@st.cache_resource
def get_client() -> Client:
    """Return a Supabase client built from ``st.secrets``.

    Cached for the lifetime of the Streamlit process so we don't reopen a
    connection on every rerun.
    """
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def __getattr__(name: str):  # noqa: D401 — module-level dunder
    """Lazy module attribute for the spec's ``from utils.db import supabase``.

    ``get_client()`` requires the Streamlit runtime to be active (it uses
    ``st.cache_resource``), so we defer evaluation to first access instead
    of binding at import time.
    """
    if name == "supabase":
        return get_client()
    raise AttributeError(f"module 'utils.db' has no attribute {name!r}")


# --------------------------------------------------------------------------- #
# Phone normalisation — Indonesian formats                                    #
# --------------------------------------------------------------------------- #


def normalize_phone(raw: str | None) -> str:
    """Convert ``08…`` / ``+62…`` / ``8…`` variants to E.164-without-plus ``62…``.

    Mirrors the backend's ``phone_utils.normalize_phone`` semantics — kept
    inline so the dashboard has no runtime dependency on backend code.
    """
    if not raw:
        return ""
    cleaned = "".join(ch for ch in str(raw) if ch.isdigit())
    if not cleaned:
        return ""
    if cleaned.startswith("62"):
        return cleaned
    if cleaned.startswith("0"):
        return "62" + cleaned[1:]
    if cleaned.startswith("8"):
        return "62" + cleaned
    return cleaned


# --------------------------------------------------------------------------- #
# Time helpers                                                                 #
# --------------------------------------------------------------------------- #


def _today_start_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


def _week_ago_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()


def _to_df(rows: list[dict[str, Any]] | None) -> pd.DataFrame:
    """Convert a Supabase ``.execute().data`` list into a DataFrame.

    Centralised so every getter handles the empty / None case identically.
    """
    return pd.DataFrame(rows or [])


# --------------------------------------------------------------------------- #
# Reads                                                                        #
# --------------------------------------------------------------------------- #


@st.cache_data(ttl=CACHE_TTL)
def get_volunteers(active_only: bool = False) -> pd.DataFrame:
    """All volunteer rows. Pass ``active_only=True`` to filter on ``is_active``."""
    db = get_client()
    query = db.table("volunteers").select(
        "id, name, full_name, phone, telegram_id, area, quota_kg, team, "
        "is_active, whatsapp_connected, last_contact_at"
    )
    if active_only:
        query = query.eq("is_active", True)
    # ``volunteers`` does not carry a ``created_at`` column in the legacy
    # schema; sort by ``name`` so the table is at least alphabetically stable.
    return _to_df(query.order("name").execute().data)


@st.cache_data(ttl=CACHE_TTL)
def get_active_missions() -> pd.DataFrame:
    """Currently-active missions with deadline + status."""
    db = get_client()
    rows = (
        db.table("missions")
        .select("id, title, description, deadline, status, created_at, created_by")
        .eq("status", "active")
        .order("deadline", desc=False)
        .execute()
        .data
    )
    df = _to_df(rows)
    if not df.empty and "deadline" in df.columns:
        df["deadline_dt"] = pd.to_datetime(df["deadline"], errors="coerce", utc=True)
        df["days_left"] = (
            df["deadline_dt"] - pd.Timestamp.now(tz="UTC")
        ).dt.days.clip(lower=0)
    return df


@st.cache_data(ttl=CACHE_TTL)
def get_missions() -> list[dict[str, Any]]:
    """All missions enriched with progress (``total_kg``, ``pct``) + deadline label.

    Optional schema columns (``target_kg``, ``sop``, ``drop_point``,
    ``emergency_contact``, ``avoid_items``, ``field_tips``, ``partner_contact``,
    ``start_date``) are surfaced when present; missing columns fall back to
    ``-`` / ``None`` so the dashboard renders gracefully on legacy schemas.
    """
    db = get_client()
    # Some legacy schemas don't carry ``created_at`` on ``missions``; fall
    # back to ``deadline`` (always present) when the order request errors.
    try:
        rows = (
            db.table("missions")
            .select("*")
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = (
            db.table("missions")
            .select("*")
            .order("deadline", desc=True)
            .execute()
            .data
            or []
        )
    if not rows:
        return []

    reports = (
        db.table("reports").select("mission_id, kg_collected").execute().data or []
    )
    totals: dict[str, float] = defaultdict(float)
    for r in reports:
        totals[r.get("mission_id")] += float(r.get("kg_collected") or 0)

    quotas = (
        db.table("volunteer_missions")
        .select("mission_id, quota_kg")
        .execute()
        .data
        or []
    )
    quota_sums: dict[str, float] = defaultdict(float)
    for q in quotas:
        quota_sums[q.get("mission_id")] += float(q.get("quota_kg") or 0)

    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for m in rows:
        mid = m["id"]
        total = round(totals.get(mid, 0.0), 2)
        # Prefer the explicit ``target_kg`` column when the schema has it.
        target = float(m.get("target_kg") or 0) or round(quota_sums.get(mid, 0.0), 2)
        pct = round((total / target * 100), 1) if target else 0.0

        deadline_raw = m.get("deadline")
        deadline_label = "-"
        if deadline_raw:
            try:
                dt = datetime.fromisoformat(
                    str(deadline_raw).replace("Z", "+00:00")
                )
                days = (dt - now).days
                if days >= 0:
                    deadline_label = (
                        f"{dt.strftime('%d %b %Y')} ({days} hari lagi)"
                    )
                else:
                    deadline_label = (
                        f"{dt.strftime('%d %b %Y')} (lewat {-days} hari)"
                    )
            except ValueError:
                pass

        out.append(
            {
                "id": mid,
                "title": m.get("title") or "Tanpa judul",
                "description": m.get("description") or "",
                "status": m.get("status") or "active",
                "deadline": deadline_raw,
                "deadline_label": deadline_label,
                "sop": m.get("sop") or "-",
                "drop_point": m.get("drop_point") or "-",
                "emergency_contact": m.get("emergency_contact") or "-",
                "avoid_items": m.get("avoid_items") or "",
                "field_tips": m.get("field_tips") or "",
                "partner_contact": m.get("partner_contact") or "",
                "start_date": m.get("start_date"),
                "target_kg": target,
                "total_kg": total,
                "pct": pct,
            }
        )
    return out


@st.cache_data(ttl=CACHE_TTL)
def get_reports(limit: int = 50) -> pd.DataFrame:
    """Most-recent reports, newest first."""
    db = get_client()
    rows = (
        db.table("reports")
        .select(
            "id, volunteer_id, mission_id, kg_collected, location, "
            "photo_url, source, is_flagged, verified, flag_reason, "
            "reported_at, is_test"
        )
        .order("reported_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    return _enrich_reports(_to_df(rows))


@st.cache_data(ttl=CACHE_TTL)
def get_today_reports() -> pd.DataFrame:
    """Reports submitted since 00:00 UTC today."""
    db = get_client()
    rows = (
        db.table("reports")
        .select(
            "id, volunteer_id, mission_id, kg_collected, location, "
            "photo_url, source, is_flagged, verified, reported_at"
        )
        .gte("reported_at", _today_start_iso())
        .order("reported_at", desc=True)
        .execute()
        .data
    )
    return _enrich_reports(_to_df(rows))


@st.cache_data(ttl=CACHE_TTL)
def get_flagged_reports() -> pd.DataFrame:
    """Unverified flagged reports awaiting fasilitator review."""
    db = get_client()
    rows = (
        db.table("reports")
        .select(
            "id, volunteer_id, mission_id, kg_collected, location, "
            "photo_url, flag_reason, reported_at"
        )
        .eq("is_flagged", True)
        .eq("verified", False)
        .order("reported_at", desc=True)
        .execute()
        .data
    )
    return _enrich_reports(_to_df(rows))


@st.cache_data(ttl=CACHE_TTL)
def get_program_stats() -> dict[str, Any]:
    """KPIs rendered on the home page.

    Returns:
        total_kg, week_kg, today_kg, total_reports,
        total_volunteers, active_volunteers, reported (today),
        pending (active volunteers without a today report),
        flagged (unverified flagged reports), active_missions,
        target_kg (sum of active assignment quotas),
        pct_target (today's total / target * 100).
    """
    db = get_client()
    volunteers = db.table("volunteers").select("id", count="exact").execute()
    active_volunteer_rows = (
        db.table("volunteers")
        .select("id")
        .eq("is_active", True)
        .execute()
        .data
        or []
    )
    active_missions = (
        db.table("missions")
        .select("id", count="exact")
        .eq("status", "active")
        .execute()
    )
    reports = (
        db.table("reports")
        .select("kg_collected, is_flagged, verified, reported_at, volunteer_id")
        .execute()
        .data
        or []
    )
    target_rows = (
        db.table("volunteer_missions")
        .select("quota_kg")
        .execute()
        .data
        or []
    )

    week_cutoff = _week_ago_iso()
    today_cutoff = _today_start_iso()

    total_kg = round(sum(float(r["kg_collected"]) for r in reports), 2)
    week_kg = round(
        sum(
            float(r["kg_collected"])
            for r in reports
            if r.get("reported_at", "") >= week_cutoff
        ),
        2,
    )
    today_kg = round(
        sum(
            float(r["kg_collected"])
            for r in reports
            if r.get("reported_at", "") >= today_cutoff
        ),
        2,
    )

    target_kg = round(sum(float(t.get("quota_kg") or 0) for t in target_rows), 2)
    pct_target = round((today_kg / target_kg * 100), 1) if target_kg else 0.0

    active_ids = {v["id"] for v in active_volunteer_rows}
    reporters_today = {
        r["volunteer_id"]
        for r in reports
        if r.get("reported_at", "") >= today_cutoff
    }
    reported = len(active_ids & reporters_today)
    pending = max(len(active_ids) - reported, 0)

    flagged = sum(
        1 for r in reports if r.get("is_flagged") and not r.get("verified")
    )

    return {
        "total_volunteers": volunteers.count or 0,
        "active_volunteers": len(active_ids),
        "active_missions": active_missions.count or 0,
        "total_reports": len(reports),
        "total_kg": total_kg,
        "week_kg": week_kg,
        "today_kg": today_kg,
        "target_kg": target_kg,
        "pct_target": pct_target,
        "reported": reported,
        "pending": pending,
        "flagged": flagged,
        "flagged_unverified": flagged,  # back-compat alias
    }


@st.cache_data(ttl=CACHE_TTL)
def get_weekly_trend() -> pd.DataFrame:
    """Last 7 days of report totals, one row per day (WIB).

    Always returns 7 rows — days with no reports surface as ``kg = 0`` so
    bar charts have a continuous x-axis.
    """
    db = get_client()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.table("reports")
        .select("kg_collected, reported_at")
        .gte("reported_at", cutoff.isoformat())
        .execute()
        .data
        or []
    )
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame({"reported_at": [], "kg_collected": []})
    df["reported_at"] = pd.to_datetime(df["reported_at"], errors="coerce", utc=True)
    df["day"] = df["reported_at"].dt.tz_convert("Asia/Jakarta").dt.date
    grouped = (
        df.groupby("day", as_index=False)["kg_collected"]
        .sum()
        .rename(columns={"kg_collected": "kg"})
    )
    # Fill missing days with 0 so the chart shows a flat day instead of a gap.
    today_local = datetime.now(JAKARTA_TZ).date()
    all_days = pd.DataFrame(
        {"day": [today_local - timedelta(days=i) for i in range(6, -1, -1)]}
    )
    out = all_days.merge(grouped, on="day", how="left").fillna({"kg": 0})
    out["day"] = pd.to_datetime(out["day"])
    out["kg"] = out["kg"].round(2)
    return out


@st.cache_data(ttl=CACHE_TTL)
def get_volunteers_with_status() -> pd.DataFrame:
    """Active volunteers + whether they reported today.

    Columns: ``id, name, area, reported`` (bool).
    """
    db = get_client()
    volunteers = (
        db.table("volunteers")
        .select("id, name, area")
        .eq("is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    today_iso = _today_start_iso()
    reports_today = (
        db.table("reports")
        .select("volunteer_id")
        .gte("reported_at", today_iso)
        .execute()
        .data
        or []
    )
    reported_ids = {r["volunteer_id"] for r in reports_today}
    df = pd.DataFrame(volunteers)
    if df.empty:
        return df.assign(reported=[])
    df["reported"] = df["id"].isin(reported_ids)
    return df


# --------------------------------------------------------------------------- #
# Enrichment                                                                   #
# --------------------------------------------------------------------------- #


@st.cache_data(ttl=CACHE_TTL)
def _volunteer_name_lookup() -> dict[str, str]:
    db = get_client()
    rows = db.table("volunteers").select("id, name").execute().data or []
    return {r["id"]: (r.get("name") or "?") for r in rows}


@st.cache_data(ttl=CACHE_TTL)
def _mission_title_lookup() -> dict[str, str]:
    db = get_client()
    rows = db.table("missions").select("id, title").execute().data or []
    return {r["id"]: (r.get("title") or "?") for r in rows}


def _enrich_reports(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    names = _volunteer_name_lookup()
    titles = _mission_title_lookup()
    df = df.copy()
    if "volunteer_id" in df.columns:
        df["volunteer_name"] = df["volunteer_id"].map(names).fillna("?")
    if "mission_id" in df.columns:
        df["mission_title"] = df["mission_id"].map(titles).fillna("?")
    if "reported_at" in df.columns:
        df["reported_at_dt"] = pd.to_datetime(
            df["reported_at"], errors="coerce", utc=True
        )
        df["reported_at_relative"] = df["reported_at_dt"].map(_humanize_delta)
    if "kg_collected" in df.columns and "kg" not in df.columns:
        df["kg"] = df["kg_collected"]
    return df


def _humanize_delta(when: pd.Timestamp | None) -> str:
    """Format a UTC timestamp as 'X menit lalu' / 'X jam lalu' / 'X hari lalu'."""
    if when is None or pd.isna(when):
        return ""
    delta = pd.Timestamp.now(tz="UTC") - when
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "baru saja"
    if minutes < 60:
        return f"{minutes} menit lalu"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} jam lalu"
    days = hours // 24
    return f"{days} hari lalu"


# --------------------------------------------------------------------------- #
# Cache invalidation                                                           #
# --------------------------------------------------------------------------- #


def clear_caches() -> None:
    """Drop every cached read. Pages call this after a mutation."""
    for fn in (
        get_volunteers,
        get_active_missions,
        get_missions,
        get_reports,
        get_today_reports,
        get_flagged_reports,
        get_program_stats,
        get_weekly_trend,
        get_volunteers_with_status,
        _volunteer_name_lookup,
        _mission_title_lookup,
    ):
        fn.clear()
