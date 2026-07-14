"""Challenges page — manage GBP challenges the bot reminds + guides on.

Backs ``action_items`` rows of ``type='challenge'``. These are the source the
bot reads (``ActionItemResolver.list_active_challenges``) to (a) remind
volunteers and (b) inject the active-challenge brief into volunteer /
fasilitator guidance prompts. No scoring here — points live in gform / panitia.

Every field is editable: judul, deskripsi (blob the bot reads verbatim),
deadline, link gform, hadiah, aktif/nonaktif.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402,F401 (auto-installs Plotly defaults)
from utils.db import supabase  # noqa: E402

st.set_page_config(page_title="Challenges — Macca", page_icon="🎯", layout="wide")
st.title("🎯 Manajemen Challenge")
st.caption(
    "Sumber tunggal challenge untuk bot: reminder + panduan volunteer. "
    "Deskripsi dibaca bot apa adanya — tulis tahapan, opsi, hashtag, tag, "
    "dan ketentuan gform selengkap mungkin. Skor bukan urusan bot."
)


# --------------------------------------------------------------------------- #
# Load                                                                         #
# --------------------------------------------------------------------------- #


def _load_challenges() -> list[dict]:
    return (
        supabase.table("action_items")
        .select("*")
        .eq("type", "challenge")
        .order("deadline", desc=False)
        .execute()
        .data
        or []
    )


challenges = _load_challenges()
today = dt.date.today()


def _as_date(raw) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _as_time(raw) -> dt.time | None:
    """Extract the time component from a deadline timestamp, if any."""
    if not raw:
        return None
    s = str(raw).replace("Z", "+00:00")
    if "T" not in s and " " not in s:
        return None  # date-only, no time
    try:
        return dt.datetime.fromisoformat(s).time().replace(second=0, microsecond=0)
    except ValueError:
        return None


# Default deadline time when unspecified — end of day ("jam 24").
_END_OF_DAY = dt.time(23, 59)


def _combine_deadline(d: dt.date | None, t: dt.time | None) -> str | None:
    """Combine date + time into a UTC ISO timestamp; default time = 23:59."""
    if not d:
        return None
    return dt.datetime.combine(
        d, t or _END_OF_DAY, tzinfo=dt.timezone.utc
    ).isoformat()


def _status(c: dict) -> str:
    """Window-aware status matching the bot's ``list_active_challenges`` logic."""
    if not c.get("is_active"):
        return "⚫ Nonaktif"
    start = _as_date(c.get("start_date"))
    deadline = _as_date(c.get("deadline"))
    if start and start > today:
        return f"🟡 Belum mulai (mulai {start:%d %b %Y})"
    if deadline and deadline < today:
        return "⏰ Selesai (lewat deadline)"
    return "🟢 Aktif"


live = [c for c in challenges if _status(c) == "🟢 Aktif"]
st.metric("Challenge aktif (dipakai bot)", len(live))
st.caption(
    "Bot pakai challenge kalau: **Aktif** + hari ini di dalam periode "
    "(mulai ≤ hari ini ≤ deadline)."
)
st.divider()


# --------------------------------------------------------------------------- #
# Edit existing                                                                #
# --------------------------------------------------------------------------- #


if not challenges:
    st.info("Belum ada challenge. Tambahkan di bawah.")
else:
    st.subheader("Daftar Challenge")
    for c in challenges:
        cid = c["id"]
        dl = _as_date(c.get("deadline"))
        dl_time = _as_time(c.get("deadline"))
        sd = _as_date(c.get("start_date"))
        with st.expander(f"{_status(c)} — {c.get('title') or '(tanpa judul)'}"):
            with st.form(f"edit_{cid}"):
                title = st.text_input("Judul", value=c.get("title") or "")
                description = st.text_area(
                    "Deskripsi (dibaca bot verbatim)",
                    value=c.get("description") or "",
                    height=280,
                )
                e1, e2, e3 = st.columns(3)
                start_date = e1.date_input(
                    "Tanggal mulai", value=sd or today
                )
                deadline_date = e2.date_input(
                    "Deadline (tgl)", value=dl or (today + dt.timedelta(days=14))
                )
                deadline_time = e3.time_input(
                    "Jam", value=dl_time or _END_OF_DAY,
                    help="Kosong / tidak diubah → default 23:59 (akhir hari).",
                )
                e4, e5 = st.columns(2)
                reward = e4.text_input("Hadiah / insentif", value=c.get("reward") or "")
                link_url = e5.text_input(
                    "Link Google Form (opsional)", value=c.get("link_url") or ""
                )
                is_active = st.toggle("Aktif", value=bool(c.get("is_active")))

                b1, b2 = st.columns([1, 1])
                save = b1.form_submit_button("💾 Simpan", type="primary")
                delete = b2.form_submit_button("🗑 Hapus")

                if save:
                    patch = {
                        "title": title.strip(),
                        "description": description.strip(),
                        "start_date": start_date.isoformat() if start_date else None,
                        "deadline": _combine_deadline(deadline_date, deadline_time),
                        "reward": reward.strip() or None,
                        "link_url": link_url.strip() or None,
                        "is_active": bool(is_active),
                    }
                    try:
                        supabase.table("action_items").update(patch).eq(
                            "id", cid
                        ).execute()
                        st.success("✅ Challenge diperbarui.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Gagal simpan: {exc}")

                if delete:
                    try:
                        supabase.table("action_items").delete().eq(
                            "id", cid
                        ).execute()
                        st.success("🗑 Challenge dihapus.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Gagal hapus: {exc}")


# --------------------------------------------------------------------------- #
# Add new                                                                      #
# --------------------------------------------------------------------------- #


st.divider()
st.subheader("➕ Tambah Challenge")

with st.form("add_challenge", clear_on_submit=True):
    n_title = st.text_input("Judul *", placeholder="contoh: Less Plastic More Life")
    n_desc = st.text_area(
        "Deskripsi *",
        placeholder=(
            "Tahapan, opsi aksi, output, hashtag wajib, akun yang di-tag, "
            "ketentuan upload + gform, deadline…"
        ),
        height=240,
    )
    a1, a2, a3 = st.columns(3)
    n_start = a1.date_input("Tanggal mulai", value=today)
    n_deadline = a2.date_input("Deadline (tgl)", value=today + dt.timedelta(days=14))
    n_deadline_time = a3.time_input(
        "Jam", value=_END_OF_DAY,
        help="Default 23:59 (akhir hari) kalau tidak diubah.",
    )
    a4, a5 = st.columns(2)
    n_reward = a4.text_input("Hadiah / insentif (opsional)")
    n_link = a5.text_input("Link Google Form (opsional)")
    n_active = st.toggle("Langsung aktifkan", value=True)

    submitted = st.form_submit_button("💾 Simpan Challenge", type="primary")
    if submitted:
        if not n_title.strip() or not n_desc.strip():
            st.error("Judul dan deskripsi wajib diisi.")
        else:
            row = {
                "type": "challenge",
                "title": n_title.strip(),
                "description": n_desc.strip(),
                "start_date": n_start.isoformat() if n_start else None,
                "deadline": _combine_deadline(n_deadline, n_deadline_time),
                "reward": n_reward.strip() or None,
                "link_url": n_link.strip() or None,
                "is_active": bool(n_active),
            }
            try:
                supabase.table("action_items").insert(row).execute()
                st.success(f"✅ Challenge '{n_title}' tersimpan!")
                st.rerun()
            except Exception as exc:
                st.error(f"Gagal simpan: {exc}")
