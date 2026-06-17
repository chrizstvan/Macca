"""Content + Quiz + Impact generator page."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402,F401 (auto-installs Plotly defaults)
from utils.api import (  # noqa: E402
    generate_content,
    generate_impact_report,
    generate_quiz,
    schedule_message,
)

st.set_page_config(page_title="Content — Macca", page_icon="📢", layout="wide")
st.title("📢 Generator Konten & Quiz")

tab1, tab2, tab3 = st.tabs(["Konten Edukasi", "Quiz Trivia", "Impact Report"])


# --------------------------------------------------------------------------- #
# TAB 1 — Content                                                              #
# --------------------------------------------------------------------------- #


with tab1:
    st.subheader("Generate Konten Lingkungan untuk Volunteer")
    topic = st.selectbox(
        "Topik",
        (
            "Fakta plastik mingguan",
            "Tips daur ulang",
            "Dampak mikroplastik",
            "Alternatif plastik",
            "Pencapaian program",
            "Motivasi & semangat",
        ),
    )
    tone = st.radio(
        "Tone", ("Semangat", "Edukatif", "Santai"), horizontal=True
    )
    audience = st.selectbox(
        "Kirim ke",
        ("Semua volunteer", "Yang belum lapor", "Tim tertentu"),
    )

    schedule_on = st.toggle(
        "Jadwalkan (kirim nanti)", value=False, key="content_schedule_toggle"
    )
    scheduled_at_iso: str | None = None
    if schedule_on:
        sc_col1, sc_col2 = st.columns(2)
        sched_date = sc_col1.date_input(
            "Tanggal kirim", value=dt.date.today(), key="content_sched_date"
        )
        sched_time = sc_col2.time_input(
            "Jam kirim",
            value=(dt.datetime.now() + dt.timedelta(hours=1)).time().replace(microsecond=0),
            key="content_sched_time",
        )
        scheduled_at_iso = dt.datetime.combine(
            sched_date, sched_time, tzinfo=dt.timezone.utc
        ).isoformat()

    if st.button("📨 Generate Konten", type="primary", key="content_generate"):
        with st.spinner("Generating…"):
            try:
                result = generate_content(
                    topic=topic, tone=tone, audience=audience
                )
                st.session_state["content_preview"] = result["content"]
            except Exception as exc:
                st.error(f"Gagal generate: {exc}")

    preview = st.session_state.get("content_preview", "")
    if preview:
        st.text_area("Preview konten:", preview, height=180, key="content_preview_box")
        if st.button("✅ Konfirmasi Kirim", type="primary", key="content_confirm"):
            with st.spinner("Mengirim / menjadwalkan…"):
                try:
                    schedule_message(
                        content=st.session_state["content_preview_box"],
                        recipient_filter=audience,
                        scheduled_at=scheduled_at_iso,
                    )
                    st.success(
                        "✅ Konten dijadwalkan!"
                        if scheduled_at_iso
                        else "✅ Konten dikirim!"
                    )
                except Exception as exc:
                    st.error(f"Gagal: {exc}")


# --------------------------------------------------------------------------- #
# TAB 2 — Quiz                                                                 #
# --------------------------------------------------------------------------- #


with tab2:
    st.subheader("Generate Quiz Trivia Plastik")
    difficulty = st.select_slider(
        "Tingkat kesulitan",
        options=("Mudah", "Sedang", "Sulit"),
        value="Sedang",
        key="quiz_difficulty",
    )
    num_options = st.radio(
        "Jumlah pilihan jawaban", (3, 4), horizontal=True, key="quiz_num_opts"
    )

    if st.button("🎲 Generate Quiz Baru", type="primary", key="quiz_generate"):
        with st.spinner("Generating…"):
            try:
                quiz = generate_quiz(
                    difficulty=difficulty, num_options=int(num_options)
                )
                st.session_state["quiz_data"] = quiz
            except Exception as exc:
                st.error(f"Gagal generate: {exc}")

    quiz_data = st.session_state.get("quiz_data")
    if quiz_data:
        st.write(f"**Pertanyaan:** {quiz_data.get('question')}")
        for opt in quiz_data.get("options") or []:
            st.write(f"- {opt}")
        with st.expander("Lihat jawaban"):
            st.write(
                f"✅ **{quiz_data.get('answer')}** — "
                f"{quiz_data.get('explanation')}"
            )

        q1, q2 = st.columns(2)
        if q1.button("📨 Kirim ke Semua Sekarang", key="quiz_send_now"):
            with st.spinner("Mengirim…"):
                try:
                    result = schedule_message(
                        quiz=quiz_data, recipient_filter="all"
                    )
                    st.success(
                        f"Quiz dikirim ke {result.get('dispatched', '?')} volunteer."
                    )
                except Exception as exc:
                    st.error(f"Gagal: {exc}")

        q2_date = q2.date_input(
            "Atau jadwalkan:", value=dt.date.today(), key="quiz_sched_date"
        )
        q2_time = q2.time_input(
            "Jam:", value=dt.time(12, 0), key="quiz_sched_time"
        )
        if q2.button("⏰ Jadwalkan Quiz", key="quiz_schedule"):
            iso = dt.datetime.combine(
                q2_date, q2_time, tzinfo=dt.timezone.utc
            ).isoformat()
            try:
                schedule_message(
                    quiz=quiz_data,
                    recipient_filter="all",
                    scheduled_at=iso,
                )
                st.success(f"Quiz dijadwalkan {iso}.")
            except Exception as exc:
                st.error(f"Gagal: {exc}")


# --------------------------------------------------------------------------- #
# TAB 3 — Impact report                                                        #
# --------------------------------------------------------------------------- #


with tab3:
    st.subheader("Generate Impact Report")
    report_type = st.radio(
        "Berdasarkan",
        ("Progress saat ini", "Target yang ingin dicapai"),
        horizontal=True,
        key="impact_type",
    )

    target_kg: float | None = None
    if report_type == "Target yang ingin dicapai":
        target_kg = st.number_input(
            "Target kg yang ingin divisualisasikan",
            value=500,
            min_value=1,
            key="impact_target",
        )

    format_out = st.multiselect(
        "Format output",
        ("Narasi teks", "Infografis (coming soon)", "Data tabel"),
        default=("Narasi teks",),
        key="impact_format",
    )

    if st.button("📊 Generate Impact Report", type="primary", key="impact_generate"):
        with st.spinner("Menghitung dampak…"):
            try:
                report = generate_impact_report(target_kg=target_kg)
                st.session_state["impact_report"] = report
            except Exception as exc:
                st.error(f"Gagal: {exc}")

    report = st.session_state.get("impact_report")
    if report:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Terkumpul", f"{report.get('total_kg', 0):g} kg")
        m2.metric("Botol Diselamatkan", f"{int(report.get('bottles', 0)):,}")
        m3.metric("CO₂ Dicegah", f"{report.get('co2_kg', 0):.1f} kg")

        if "Narasi teks" in format_out:
            st.text_area(
                "Narasi:",
                report.get("narrative", ""),
                height=200,
                key="impact_narrative",
            )

        if "Data tabel" in format_out:
            st.dataframe(
                [
                    {"metrik": "Total terkumpul (kg)", "nilai": report.get("total_kg")},
                    {"metrik": "Botol diselamatkan", "nilai": report.get("bottles")},
                    {"metrik": "CO₂ dicegah (kg)", "nilai": report.get("co2_kg")},
                    *(
                        [{"metrik": "Target (kg)", "nilai": target_kg}]
                        if target_kg
                        else []
                    ),
                ],
                hide_index=True,
                use_container_width=True,
            )

        if "Infografis (coming soon)" in format_out:
            st.info("Infografis belum tersedia — coming soon.")
