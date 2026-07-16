"""Macca dashboard — main overview page.

Run from the project root:
    .venv/bin/streamlit run dashboard/app.py

Pages (left sidebar):
    1_Volunteers.py    — volunteer management
    4_Messages.py      — send messages & reminders
    6_Content.py       — content & quiz generator
    7_Persona.py       — agent persona configurator
    8_Action_Items.py  — all reminder targets incl. challenges (fully editable:
                         deadline+time, challenge start/window, reward, links)
    9_Settings.py      — program settings

Archived in ``dashboard/_archived_pages/``:
    2_Missions.py, 3_Reports.py, 5_Ranking.py — kg-based; program is
    challenge-only now. 2_Challenges.py — merged into 8_Action_Items.py.
    Move back into ``pages/`` to re-enable.

Configuration:
    Copy ``.streamlit/secrets.toml.example`` to ``.streamlit/secrets.toml``
    and fill in SUPABASE_URL / SUPABASE_KEY / API_URL.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Make ``dashboard/utils`` importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import datetime as dt  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402,F401  (import auto-installs Plotly theme)
from utils.db import (  # noqa: E402
    clear_caches,
    get_volunteers,
    supabase,
)

AUTO_REFRESH_INTERVAL_S = 60

TYPE_LABELS = {
    "challenge": "🎯 Challenge",
    "submission": "📤 Submit",
    "kelas": "📚 Kelas",
    "presensi": "✋ Presensi",
    "pre_test": "📝 Pre-Test",
    "post_test": "📝 Post-Test",
    "tautan": "🔗 Tautan",
    "buku_saku": "📖 Buku Saku",
    "bahi": "🧠 BAHI",
}

st.set_page_config(
    page_title="Generasi Bebas Plastik",
    page_icon="🌱",
    layout="wide",
)

st.title("🌱 Generasi Bebas Plastik — Dashboard")


# --------------------------------------------------------------------------- #
# Data                                                                         #
# --------------------------------------------------------------------------- #


def _today() -> str:
    return dt.date.today().isoformat()


def _active_items() -> list[dict]:
    try:
        return (
            supabase.table("action_items")
            .select("*")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
    except Exception:
        return []


def _when(item: dict) -> str | None:
    """Sort/display date: deadline or scheduled_at (date part)."""
    raw = item.get("deadline") or item.get("scheduled_at")
    return str(raw)[:10] if raw else None


def _fmt(raw) -> str:
    s = str(raw)
    if ("T" in s or " " in s) and len(s) >= 16:
        return f"{s[:10]} {s[11:16]}"
    return s[:10]


def _challenge_running(c: dict, today: str) -> bool:
    start = str(c["start_date"])[:10] if c.get("start_date") else None
    end = str(c["deadline"])[:10] if c.get("deadline") else None
    return not (start and start > today) and not (end and end < today)


# --------------------------------------------------------------------------- #
# ROW 1 — headline counts                                                      #
# --------------------------------------------------------------------------- #


def _metric_row(items: list[dict]) -> None:
    today = _today()
    vols = get_volunteers(active_only=True)
    active_vol = 0 if vols.empty else len(vols)
    challenges = [i for i in items if i.get("type") == "challenge"]
    running = [c for c in challenges if _challenge_running(c, today)]

    c1, c2, c3 = st.columns(3)
    c1.metric("Volunteer Aktif", active_vol)
    c2.metric("Challenge Berjalan", len(running))
    c3.metric("Action Item Aktif", len(items))


# --------------------------------------------------------------------------- #
# ROW 2 — activity feed (running now + upcoming)                               #
# --------------------------------------------------------------------------- #


def _activity_feed(items: list[dict]) -> None:
    today = _today()

    def _line(item: dict, extra: str = "") -> None:
        label = TYPE_LABELS.get(item.get("type"), item.get("type"))
        when = item.get("deadline") or item.get("scheduled_at")
        when_str = f" · ⏰ {_fmt(when)}" if when else ""
        st.markdown(f"**{label} — {item.get('title') or '?'}**{extra}{when_str}")
        loc = item.get("location")
        if loc:
            st.caption(f"📍 {loc}")

    running: list[dict] = []
    upcoming: list[dict] = []
    for it in items:
        if it.get("type") == "challenge":
            (running if _challenge_running(it, today) else upcoming).append(it)
        else:
            when = _when(it)
            (upcoming if (when and when > today) else running).append(it)

    running.sort(key=lambda x: _when(x) or "9999")
    upcoming.sort(key=lambda x: _when(x) or "9999")

    left, right = st.columns(2)
    with left:
        st.subheader("🟢 Sedang Berjalan")
        if not running:
            st.info("Tidak ada activity yang sedang berjalan.")
        for it in running:
            _line(it)
            st.divider()
    with right:
        st.subheader("🟡 Akan Datang")
        if not upcoming:
            st.info("Tidak ada activity terjadwal.")
        for it in upcoming:
            start = it.get("start_date")
            extra = f" · mulai {str(start)[:10]}" if it.get("type") == "challenge" and start else ""
            _line(it, extra)
            st.divider()


# --------------------------------------------------------------------------- #
# Controls — refresh                                                           #
# --------------------------------------------------------------------------- #


def _controls() -> None:
    c1, c2, c3 = st.columns([1, 1, 4])
    if c1.button("🔄 Refresh Data"):
        clear_caches()
        st.rerun()
    auto = c2.toggle(
        f"Auto-refresh {AUTO_REFRESH_INTERVAL_S}s",
        value=False,
        help=(
            "Aktifkan untuk auto-refresh setiap "
            f"{AUTO_REFRESH_INTERVAL_S} detik. Halaman akan reload otomatis."
        ),
    )
    c3.caption(f"Cache TTL 30 detik · {pd.Timestamp.now(tz='Asia/Jakarta'):%d %b %Y, %H:%M WIB}")
    return auto


# --------------------------------------------------------------------------- #
# Render                                                                       #
# --------------------------------------------------------------------------- #


_items = _active_items()
_metric_row(_items)
st.divider()
_activity_feed(_items)
st.divider()
auto = _controls()

if auto:
    time.sleep(AUTO_REFRESH_INTERVAL_S)
    clear_caches()
    st.rerun()
