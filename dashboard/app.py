"""Macca dashboard — main overview page.

Run from the project root:
    .venv/bin/streamlit run dashboard/app.py

Pages (left sidebar):
    1_Volunteers.py    — volunteer management
    2_Missions.py      — mission management
    3_Reports.py       — report review
    4_Messages.py      — send messages & reminders
    5_Ranking.py       — leaderboard & scores
    6_Content.py       — content & quiz generator
    7_Persona.py       — agent persona configurator

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

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402  (import auto-installs Plotly theme)
from utils.db import (  # noqa: E402
    clear_caches,
    get_program_stats,
    get_today_reports,
    get_volunteers_with_status,
    get_weekly_trend,
)

PRIMARY_COLOR = theme.ACCENT_LEAF
AUTO_REFRESH_INTERVAL_S = 60
VOLUNTEERS_PER_ROW = 10

st.set_page_config(
    page_title="Generasi Bebas Plastik",
    page_icon="🌱",
    layout="wide",
)

st.title("🌱 Generasi Bebas Plastik — Dashboard")


# --------------------------------------------------------------------------- #
# ROW 1 — KPI metric cards                                                     #
# --------------------------------------------------------------------------- #


def _metric_row() -> None:
    stats = get_program_stats()
    active_total = stats["active_volunteers"] or 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Total Terkumpul",
        f"{stats['total_kg']:g} kg",
        f"{stats['pct_target']}% dari target hari ini",
    )
    col2.metric("Sudah Lapor", f"{stats['reported']}/{active_total}")
    col3.metric(
        "Belum Lapor",
        stats["pending"],
        delta_color="inverse",
    )
    col4.metric(
        "Perlu Dicek",
        stats["flagged"],
        delta_color="inverse",
    )


# --------------------------------------------------------------------------- #
# ROW 2 — weekly trend + recent reports feed                                   #
# --------------------------------------------------------------------------- #


def _trend_and_feed() -> None:
    left, right = st.columns([2, 1])

    with left:
        weekly = get_weekly_trend()
        fig = px.bar(
            weekly,
            x="day",
            y="kg",
            title="Tren Pengumpulan 7 Hari Terakhir",
            labels={"day": "Tanggal (WIB)", "kg": "Kg"},
            color_discrete_sequence=[PRIMARY_COLOR],
        )
        fig.update_layout(
            margin=dict(l=10, r=10, t=40, b=10),
            height=340,
            xaxis_tickformat="%d %b",
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Laporan Terbaru")
        reports = get_today_reports()
        if reports.empty:
            st.info("Belum ada laporan hari ini.")
            return
        for _, r in reports.head(8).iterrows():
            kg = float(r.get("kg") or 0)
            st.write(
                f"✅ **{r.get('volunteer_name', '?')}** — {kg:g} kg di "
                f"{r.get('location') or '-'}"
            )
            st.caption(r.get("reported_at_relative") or "")


# --------------------------------------------------------------------------- #
# ROW 3 — volunteer status grid                                                #
# --------------------------------------------------------------------------- #


def _volunteer_grid() -> None:
    st.subheader("Status Volunteer Hari Ini")
    volunteers = get_volunteers_with_status()
    if volunteers.empty:
        st.info("Belum ada volunteer aktif.")
        return

    dot_tmpl = (
        "<div style='display:flex;justify-content:center;align-items:center;"
        "height:28px'>"
        "<span style='width:14px;height:14px;border-radius:50%;background:{color};"
        "box-shadow:0 0 6px {color}55'></span></div>"
    )

    rows = volunteers.to_dict(orient="records")
    cols = st.columns(VOLUNTEERS_PER_ROW)
    for i, v in enumerate(rows):
        if i and i % VOLUNTEERS_PER_ROW == 0:
            cols = st.columns(VOLUNTEERS_PER_ROW)
        color = theme.STATUS_OK if v.get("reported") else theme.STATUS_BAD
        with cols[i % VOLUNTEERS_PER_ROW]:
            st.markdown(dot_tmpl.format(color=color), unsafe_allow_html=True)
            st.caption((v.get("name") or "?")[:10])

    # Legend — coloured dots inline so the key matches the grid above.
    legend = (
        f"<span style='color:{theme.TEXT_MUTED}'>"
        f"<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
        f"background:{theme.STATUS_OK};margin-right:6px'></span>sudah lapor"
        "&nbsp;&nbsp;·&nbsp;&nbsp;"
        f"<span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
        f"background:{theme.STATUS_BAD};margin-right:6px'></span>belum lapor"
        "</span>"
    )
    st.markdown(legend, unsafe_allow_html=True)


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


_metric_row()
st.divider()
_trend_and_feed()
st.divider()
_volunteer_grid()
st.divider()
auto = _controls()

if auto:
    time.sleep(AUTO_REFRESH_INTERVAL_S)
    clear_caches()
    st.rerun()
