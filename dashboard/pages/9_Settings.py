"""Program settings page — reminder send delay + misc toggles.

Reads/writes the ``fasilitator_context`` key/value store — the SAME store the
bot reads at runtime (``FasilitatorContextRepository.get``). ``ScheduleParser``
reads ``reminder_delay_hours`` for the default-delay path; the education draft
job reads ``enable_news_search``. Writing anywhere else (e.g. a separate
``program_settings`` table) would leave these knobs disconnected from the bot.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402,F401 (auto-installs Plotly defaults)
from utils.db import supabase  # noqa: E402

st.set_page_config(page_title="Pengaturan — Macca", page_icon="⚙️", layout="wide")

_SETTINGS_TABLE = "fasilitator_context"

# Mirror of backend reporting_flag.DEFAULT_OFF_MESSAGE — kept inline so the
# dashboard has no runtime dependency on backend code.
DEFAULT_OFF_MESSAGE = (
    "Silakan isi form report atau hubungi fasilitator untuk submit reportmu :)"
)


def _get_setting(key: str, default: str | None = None) -> str | None:
    rows = (
        supabase.table(_SETTINGS_TABLE)
        .select("value")
        .eq("key", key)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0]["value"] if rows else default


def _set_setting(key: str, value: str) -> None:
    # on_conflict="key" matches the backend adapter — upsert by key, no dupes.
    supabase.table(_SETTINGS_TABLE).upsert(
        {"key": key, "value": value}, on_conflict="key"
    ).execute()


st.title("⚙️ Pengaturan Program")

st.subheader("Pengiriman Reminder")

st.caption(
    "Saat kamu setujui draft reminder dengan ketik 'kirim' saja (tanpa sebut "
    "waktu), reminder dikirim setelah jeda default ini. Kamu tetap bisa sebut "
    "waktu spesifik per reminder, contoh: 'kirim 24 jam lagi' atau "
    "'kirim 6 Juli jam 7 malam' atau 'kirim sekarang'."
)

# Load current default delay (guard against a non-numeric stored value).
try:
    current_delay = int(_get_setting("reminder_delay_hours") or 8)
except (TypeError, ValueError):
    current_delay = 8
current_delay = max(6, min(current_delay, 12))

delay = st.slider(
    "Jeda default pengiriman reminder (jam)",
    min_value=6,
    max_value=12,
    value=current_delay,
    help="Hanya berlaku saat kamu ketik 'kirim' tanpa menyebut waktu spesifik.",
)

st.info(
    f"Default: reminder dikirim {delay} jam setelah disetujui (saat ketik "
    f"'kirim' saja). Untuk waktu lain, sebut langsung saat approve."
)

if st.button("💾 Simpan", type="primary"):
    _set_setting("reminder_delay_hours", str(delay))
    st.success(f"✅ Jeda default diatur ke {delay} jam.")

st.divider()
st.subheader("Pelaporan Volunteer")
st.caption(
    "Matikan untuk menghentikan SEMUA laporan via WA — volunteer maupun relay "
    "fasilitator — sekaligus. Data lama, ranking, dan impact tidak terpengaruh. "
    "Saat dinyalakan lagi, laporan langsung jalan."
)

new_reporting = st.toggle(
    "Aktifkan pelaporan via WhatsApp (volunteer + relay fasilitator)",
    value=(_get_setting("enable_reporting", "true") != "false"),
    help="Kalau dimatikan, volunteer TIDAK bisa lapor via chat DAN fasilitator "
    "TIDAK bisa relay laporan. Semua diarahkan ke pesan di bawah. "
    "Google Form tetap jalan sebagai cadangan.",
)

if not new_reporting:
    st.warning(
        "Pelaporan via WhatsApp MATI. Volunteer & relay akan menerima pesan "
        "pengalihan di bawah."
    )

# Custom off-message — fasilitator isi link form + kata-kata di sini.
st.markdown("**Pesan saat pelaporan dimatikan**")
st.caption("Isi dengan kata-kata kamu + link Google Form report (kalau sudah ada).")
new_msg = st.text_area(
    "Pesan pengalihan",
    value=_get_setting("reporting_off_message", DEFAULT_OFF_MESSAGE),
    height=100,
    placeholder=(
        "Contoh: Halo! Untuk submit report, isi form ini ya: "
        "https://forms.gle/xxxx  Atau hubungi fasilitator. Terima kasih!"
    ),
)

if st.button("Simpan Pengaturan Pelaporan", type="primary"):
    _set_setting("enable_reporting", "true" if new_reporting else "false")
    _set_setting("reporting_off_message", new_msg.strip() or DEFAULT_OFF_MESSAGE)
    status = "AKTIF" if new_reporting else "MATI"
    st.success(f"Tersimpan! Pelaporan sekarang: {status}")

# Live preview of what a volunteer sees when reporting is off.
if not new_reporting:
    st.markdown("**Preview pesan yang diterima volunteer:**")
    st.info(new_msg)

st.divider()
st.markdown("**Contoh perintah penjadwalan saat approve draft:**")
st.code(
    """kirim                      → default (jeda di atas)
kirim sekarang             → langsung
kirim 24 jam lagi          → 24 jam dari sekarang
kirim 3 hari lagi          → 3 hari dari sekarang
kirim besok jam 8 pagi     → besok 08:00
kirim 6 Juli jam 7 malam   → 6 Juli 19:00""",
    language=None,
)

# Optional: news search toggle.
st.divider()
st.subheader("Pengaturan Lain")
news_toggle = st.toggle(
    "Aktifkan pencarian berita iklim/plastik terkini",
    value=(_get_setting("enable_news_search") == "true"),
    help="Jika aktif, agent bisa cari berita terbaru saat volunteer bertanya.",
)
if st.button("Simpan pengaturan lain"):
    _set_setting("enable_news_search", str(news_toggle).lower())
    st.success("✅ Tersimpan.")
