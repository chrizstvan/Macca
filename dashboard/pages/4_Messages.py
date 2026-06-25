"""Messages page — bulk broadcast + reminder shortcut."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import api, db, theme  # noqa: E402,F401 (theme auto-installs Plotly)

st.set_page_config(page_title="Messages — Macca", page_icon="📣", layout="wide")
st.title("📣 Messages")

st.caption(
    "Triggers the same backend pipeline as the chat-driven /broadcast and "
    "/remind commands, so messages obey the active channel routing + retry "
    "logic."
)

tab_broadcast, tab_reminder = st.tabs(["📢 Broadcast", "🔔 Reminder"])

# --------------------------------------------------------------------------- #
# Broadcast                                                                    #
# --------------------------------------------------------------------------- #

with tab_broadcast:
    st.subheader("Broadcast ke semua volunteer aktif")
    text = st.text_area(
        "Pesan",
        placeholder="cth: Besok ada evaluasi jam 10 di balai warga",
        height=140,
    )
    channel = st.selectbox(
        "Channel",
        ("(default — sesuai ACTIVE_CHANNEL)", "whatsapp", "telegram", "both"),
    )
    if st.button("Kirim broadcast", type="primary", disabled=not text.strip()):
        channel_payload = None if channel.startswith("(default") else channel
        with st.spinner("Mengirim broadcast…"):
            try:
                result = api.broadcast(text.strip(), channel=channel_payload)
                st.success(
                    f"Broadcast terkirim ke {result.get('dispatched', '?')} "
                    "volunteer."
                )
            except Exception as exc:
                st.error(f"Gagal: {exc}")

# --------------------------------------------------------------------------- #
# Reminder                                                                     #
# --------------------------------------------------------------------------- #

with tab_reminder:
    st.subheader("Kirim reminder progress")
    only_non_reporters = st.checkbox(
        "Hanya yang belum lapor hari ini",
        value=True,
    )
    volunteers = db.get_volunteers(active_only=True)
    selected_names = st.multiselect(
        "Pilih volunteer (kosongkan = semua aktif)",
        options=volunteers["name"].dropna().tolist() if not volunteers.empty else [],
        placeholder="Klik satu / beberapa nama…",
    )
    if st.button("Kirim reminder", type="primary"):
        ids = (
            volunteers[volunteers["name"].isin(selected_names)]["id"].tolist()
            if selected_names
            else []
        )
        with st.spinner("Mengirim reminder…"):
            try:
                result = api.send_reminder(ids, only_non_reporters=only_non_reporters)
                st.success(
                    f"Reminder terkirim ke {result.get('dispatched', '?')} "
                    "volunteer."
                )
            except Exception as exc:
                st.error(f"Gagal: {exc}")
