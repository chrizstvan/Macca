"""Ranking page — leaderboard + score breakdown + recalc trigger."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402  (auto-installs Plotly defaults)
from utils.db import clear_caches, supabase  # noqa: E402

st.set_page_config(page_title="Ranking — Macca", page_icon="🏆", layout="wide")
st.title("🏆 Ranking Volunteer")


# --------------------------------------------------------------------------- #
# LEADERBOARD                                                                  #
# --------------------------------------------------------------------------- #


scores = (
    supabase.table("volunteer_scores")
    .select("*, volunteers(name, area)")
    .order("rank")
    .execute()
    .data
    or []
)

if not scores:
    st.info(
        "Belum ada skor terhitung. Klik **Hitung Ulang Ranking** untuk menjalankan "
        "``RankingCalculator.update_all_rankings()`` sekarang."
    )
else:
    df = pd.DataFrame(scores)
    df["medal"] = df["rank"].map({1: "🥇", 2: "🥈", 3: "🥉"}).fillna("")
    df["display_name"] = (
        df["medal"].astype(str) + " "
        + df["volunteers"].apply(
            lambda x: (x or {}).get("name") or "?"
        )
    ).str.strip()
    df["area"] = df["volunteers"].apply(lambda x: (x or {}).get("area") or "-")

    st.dataframe(
        df[["rank", "display_name", "area", "total_score", "impact_score", "quiz_score"]],
        column_config={
            "rank": "Peringkat",
            "display_name": "Volunteer",
            "area": "Area",
            "total_score": st.column_config.ProgressColumn(
                "Skor Total", max_value=100, format="%.1f"
            ),
            "impact_score": st.column_config.NumberColumn(
                "Impact (95%)", format="%.1f"
            ),
            "quiz_score": st.column_config.NumberColumn(
                "Quiz (5%)", format="%.1f"
            ),
        },
        hide_index=True,
        use_container_width=True,
    )

    # ------------------------------------------------------------------ #
    # SCORE BREAKDOWN CHART                                              #
    # ------------------------------------------------------------------ #

    fig = px.bar(
        df.head(10),
        x="display_name",
        y=["impact_score", "quiz_score"],
        title="Top 10 Volunteer — Breakdown Skor",
        labels={"value": "Skor", "variable": "Komponen", "display_name": "Volunteer"},
        color_discrete_map={
            "impact_score": theme.ACCENT_LEAF,
            "quiz_score": theme.ACCENT_CLAY,
        },
    )
    fig.update_layout(barmode="stack", height=380)
    st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------- #
# RECALCULATE BUTTON                                                           #
# --------------------------------------------------------------------------- #


st.divider()
if st.button("🔄 Hitung Ulang Ranking", type="primary"):
    from utils.api import recalculate_rankings

    with st.spinner("Menghitung ulang skor + ranking…"):
        try:
            recalculate_rankings()
            clear_caches()
            st.success("Ranking diperbarui!")
            st.rerun()
        except Exception as exc:
            st.error(f"Gagal: {exc}")
