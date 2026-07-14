"""Reports page — recent reports + flagged-review queue + photo preview."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import db, theme  # noqa: E402,F401 (theme auto-installs Plotly)

st.set_page_config(page_title="Reports — Macca", page_icon="📦", layout="wide")
st.title("📦 Reports")

scope = st.radio(
    "Scope",
    ("Hari ini", "Terbaru (50)", "Flagged (perlu review)"),
    horizontal=True,
)

if scope == "Hari ini":
    reports = db.get_today_reports()
elif scope == "Flagged (perlu review)":
    reports = db.get_flagged_reports()
else:
    reports = db.get_reports(limit=50)

if reports.empty:
    st.info("Tidak ada laporan untuk scope ini.")
    st.stop()

st.caption(f"{len(reports)} baris")

# --------------------------------------------------------------------------- #
# Table                                                                        #
# --------------------------------------------------------------------------- #

table_cols = [
    c
    for c in (
        "reported_at", "volunteer_name", "mission_title", "kg_collected",
        "location", "source", "is_flagged", "verified", "flag_reason",
    )
    if c in reports.columns
]
st.dataframe(reports[table_cols], hide_index=True, use_container_width=True)

# --------------------------------------------------------------------------- #
# Inspect a single report                                                      #
# --------------------------------------------------------------------------- #

st.divider()
st.subheader("🔍 Detail laporan")

report_labels = [
    f"{r.get('reported_at', '')[:19]} — {r.get('volunteer_name', '?')} "
    f"({float(r.get('kg_collected') or 0):g} kg)"
    for r in reports.to_dict(orient="records")
]
if not report_labels:
    st.stop()

idx = st.selectbox(
    "Pilih baris",
    options=range(len(report_labels)),
    format_func=lambda i: report_labels[i],
)
row = reports.iloc[idx]

meta_col, photo_col = st.columns([1, 1])
with meta_col:
    st.json(
        {
            k: (v if not hasattr(v, "isoformat") else v.isoformat())
            for k, v in row.items()
            if k not in {"reported_at_dt"}
        }
    )
with photo_col:
    photo_url = row.get("photo_url")
    if photo_url:
        st.image(photo_url, caption=row.get("location") or "")
    else:
        st.info("Laporan ini tidak menyertakan foto.")
