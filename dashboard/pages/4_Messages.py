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


# Emoji labels per action-item type (mirrors the Action Items page).
_TYPE_LABELS = {
    "challenge": "🎯 Challenge",
    "submission": "📤 Submit Laporan",
    "kelas": "📚 Kelas",
    "presensi": "✋ Presensi",
    "pre_test": "📝 Pre-Test",
    "post_test": "📝 Post-Test",
    "tautan": "🔗 Tautan",
    "buku_saku": "📖 Buku Saku",
    "bahi": "🧠 BAHI",
}


def _active_action_items() -> list[dict]:
    """All active action items (for reminder prefill) — same source the bot reads."""
    try:
        return (
            db.supabase.table("action_items")
            .select("type, title, description, deadline, scheduled_at, link_url, location")
            .eq("is_active", True)
            .order("deadline", desc=False)
            .execute()
            .data
            or []
        )
    except Exception:
        return []


def _reminder_text(item: dict) -> str:
    """Compose a type-aware reminder prefill from an action item."""
    title = item.get("title") or "?"
    dl = None
    if item.get("deadline"):
        s = str(item["deadline"])
        hm = s[11:16] if ("T" in s or " " in s) and len(s) >= 16 else ""
        dl = f"{s[:10]} {hm}".strip() if hm else s[:10]
    sched = str(item.get("scheduled_at"))[:16].replace("T", " ") if item.get("scheduled_at") else None
    link = item.get("link_url")
    loc = item.get("location")
    t = item.get("type")

    if t == "challenge":
        base = f"Jangan lupa ikut challenge *{title}*"
        if dl:
            base += f", deadline {dl}"
        return base + ". Yuk lanjutkan progresnya! 🌱"
    if t == "submission":
        base = f"Jangan lupa submit *{title}*"
        if link:
            base += f": {link}"
        if dl:
            base += f" (deadline {dl})"
        return base + " ya! 📤"
    if t in ("pre_test", "post_test"):
        base = f"Jangan lupa isi *{title}*"
        if link:
            base += f": {link}"
        if dl:
            base += f" sebelum {dl}"
        return base + " 📝"
    if t == "kelas":
        base = f"Ada kelas *{title}*"
        if sched:
            base += f" pada {sched}"
        if loc:
            base += f" di {loc}"
        return base + ". Sampai jumpa! 📚"
    if t == "presensi":
        base = f"Jangan lupa presensi *{title}*"
        if sched:
            base += f" ({sched})"
        return base + " ✋"
    if t in ("tautan", "buku_saku"):
        base = f"Cek *{title}*"
        if link:
            base += f": {link}"
        return base + " 🔗"
    if t == "bahi":
        base = f"🧠 Belajar Apa Hari Ini: *{title}*"
        if link:
            base += f"\n{link}"
        return base + "\nYuk luangkan waktu belajar sebentar ya! 🌱"
    # Fallback
    return f"Reminder: *{title}*" + (f" (deadline {dl})" if dl else "")


with tab_reminder:
    st.subheader("Kirim reminder ke volunteer")
    st.caption(
        "Reminder bebas atau dari action item (challenge, submit, kelas, "
        "presensi, test, tautan, buku saku). Nama volunteer otomatis disisipkan "
        "di depan pesan."
    )

    items = _active_action_items()
    prefill = ""
    if items:
        labels = ["(tulis sendiri)"] + [
            f"{_TYPE_LABELS.get(it.get('type'), it.get('type'))} — {it.get('title')}"
            for it in items
        ]
        picked = st.selectbox("Ambil dari action item (opsional)", labels)
        if picked != "(tulis sendiri)":
            idx = labels.index(picked) - 1  # offset for the leading "(tulis sendiri)"
            prefill = _reminder_text(items[idx])

    message = st.text_area(
        "Isi reminder",
        value=prefill,
        placeholder="cth: Jangan lupa upload konten challenge sebelum deadline ya!",
        height=140,
    )

    volunteers = db.get_volunteers(active_only=True)
    selected_names = st.multiselect(
        "Pilih volunteer (kosongkan = semua aktif)",
        options=volunteers["name"].dropna().tolist() if not volunteers.empty else [],
        placeholder="Klik satu / beberapa nama…",
    )

    if st.button("Kirim reminder", type="primary", disabled=not message.strip()):
        ids = (
            volunteers[volunteers["name"].isin(selected_names)]["id"].tolist()
            if selected_names
            else []
        )
        with st.spinner("Mengirim reminder…"):
            try:
                result = api.send_reminder(ids, message=message.strip())
                st.success(
                    f"Reminder terkirim ke {result.get('dispatched', '?')} "
                    "volunteer."
                )
            except Exception as exc:
                st.error(f"Gagal: {exc}")
