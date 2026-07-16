"""Action Items page — the single home for every reminder target the bot uses.

Backs the ``action_items`` table that ``ActionItemResolver`` + the reminder /
challenge-guidance flows read from. Fasilitator manages challenge / submission /
kelas / presensi / test / tautan / buku-saku items here; the bot resolves them
by title ("ingetin <judul>") and, for challenges, injects the brief into
volunteer guidance while inside the ``start_date … deadline`` window.

Every item is fully editable (including deadline date + time).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402,F401 (auto-installs Plotly defaults)
from utils.db import supabase  # noqa: E402

st.set_page_config(page_title="Action Items — Macca", page_icon="📌", layout="wide")
st.title("📌 Action Items")
st.caption(
    "Kelola semua target reminder: challenge, submit laporan, kelas, presensi, "
    "test, tautan, buku saku. Bot pakai ini buat reminder + panduan challenge."
)

TYPE_LABELS = {
    "challenge": "🎯 Challenge",
    "submission": "📤 Submit Laporan",
    "kelas": "📚 Jadwal Kelas",
    "presensi": "✋ Presensi",
    "pre_test": "📝 Pre-Test",
    "post_test": "📝 Post-Test",
    "tautan": "🔗 Tautan Penting",
    "buku_saku": "📖 Buku Saku",
    "bahi": "🧠 BAHI (Belajar Apa Hari Ini)",
}

LINK_TYPES = {"submission", "pre_test", "post_test", "tautan", "buku_saku", "bahi"}
DEADLINE_TYPES = {"challenge", "submission", "presensi", "pre_test", "post_test"}
SCHED_TYPES = {"kelas", "presensi"}

_END_OF_DAY = dt.time(23, 59)
today = dt.date.today()


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _as_date(raw) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _as_time(raw) -> dt.time | None:
    if not raw:
        return None
    s = str(raw).replace("Z", "+00:00")
    if "T" not in s and " " not in s:
        return None
    try:
        return dt.datetime.fromisoformat(s).time().replace(second=0, microsecond=0)
    except ValueError:
        return None


def _combine(d: dt.date | None, t: dt.time | None) -> str | None:
    if not d:
        return None
    return dt.datetime.combine(d, t or _END_OF_DAY, tzinfo=dt.timezone.utc).isoformat()


def _fmt_deadline(raw) -> str:
    s = str(raw)
    if ("T" in s or " " in s) and len(s) >= 16:
        return f"{s[:10]} {s[11:16]}"
    return s[:10]


def _challenge_status(item: dict) -> str:
    if not item.get("is_active"):
        return "⚫ Nonaktif"
    start = _as_date(item.get("start_date"))
    deadline = _as_date(item.get("deadline"))
    if start and start > today:
        return f"🟡 Belum mulai ({start:%d %b})"
    if deadline and deadline < today:
        return "⏰ Selesai"
    return "🟢 Aktif"


def _render_fields(item_type: str, d: dict, kp: str) -> dict:
    """Render type-adaptive inputs, return a payload dict (without ``type``)."""
    payload: dict = {}
    payload["title"] = st.text_input("Judul *", value=d.get("title") or "", key=f"{kp}_title")
    payload["description"] = st.text_area(
        "Deskripsi", value=d.get("description") or "", height=160, key=f"{kp}_desc"
    )

    if item_type in LINK_TYPES:
        payload["link_url"] = (
            st.text_input("Link URL", value=d.get("link_url") or "", key=f"{kp}_link").strip()
            or None
        )

    if item_type in DEADLINE_TYPES:
        c1, c2 = st.columns(2)
        dd = c1.date_input(
            "Deadline (tanggal)", value=_as_date(d.get("deadline")) or today, key=f"{kp}_dld"
        )
        dtm = c2.time_input(
            "Jam deadline",
            value=_as_time(d.get("deadline")) or _END_OF_DAY,
            key=f"{kp}_dlt",
            help="Default 23:59 (akhir hari) kalau tidak diubah.",
        )
        payload["deadline"] = _combine(dd, dtm)

    if item_type == "challenge":
        payload["start_date"] = (
            st.date_input(
                "Tanggal mulai", value=_as_date(d.get("start_date")) or today, key=f"{kp}_start"
            ).isoformat()
        )
        payload["reward"] = (
            st.text_input(
                "Hadiah / insentif", value=d.get("reward") or "", key=f"{kp}_reward"
            ).strip()
            or None
        )

    if item_type in SCHED_TYPES:
        s1, s2 = st.columns(2)
        sd = s1.date_input(
            "Tanggal acara", value=_as_date(d.get("scheduled_at")) or today, key=f"{kp}_schd"
        )
        stime = s2.time_input(
            "Waktu acara", value=_as_time(d.get("scheduled_at")) or dt.time(9, 0), key=f"{kp}_scht"
        )
        payload["scheduled_at"] = _combine(sd, stime)
        payload["location"] = (
            st.text_input(
                "Lokasi / Link (kalau online)", value=d.get("location") or "", key=f"{kp}_loc"
            ).strip()
            or None
        )

    return payload


# --------------------------------------------------------------------------- #
# Tabs                                                                         #
# --------------------------------------------------------------------------- #


tab_list, tab_add = st.tabs(["Daftar Action Items", "Tambah Baru"])


with tab_add:
    st.subheader("Tambah Action Item")
    add_type = st.selectbox(
        "Jenis",
        options=list(TYPE_LABELS.keys()),
        format_func=lambda x: TYPE_LABELS[x],
        key="add_type",
    )
    with st.form("add_item", clear_on_submit=True):
        payload = _render_fields(add_type, {}, kp="add")
        if st.form_submit_button("💾 Simpan Action Item", type="primary"):
            if not (payload.get("title") or "").strip():
                st.error("Judul wajib diisi.")
            else:
                row = {"type": add_type, "is_active": True, **payload}
                row["title"] = row["title"].strip()
                row["description"] = (row.get("description") or "").strip() or None
                try:
                    supabase.table("action_items").insert(row).execute()
                    st.success(f"✅ {TYPE_LABELS[add_type]} '{row['title']}' tersimpan!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gagal simpan: {exc}")


with tab_list:
    items = (
        supabase.table("action_items")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    if not items:
        st.info("Belum ada action item. Tambahkan di tab 'Tambah Baru'.")
    else:
        filter_type = st.multiselect(
            "Filter jenis",
            options=list(TYPE_LABELS.keys()),
            format_func=lambda x: TYPE_LABELS[x],
            default=[],
        )
        for item in items:
            if filter_type and item["type"] not in filter_type:
                continue
            iid = item["id"]
            itype = item["type"]
            label = TYPE_LABELS.get(itype, itype)
            head = f"{label} — {item.get('title') or '(tanpa judul)'}"
            if itype == "challenge":
                head = f"{_challenge_status(item)} · {head}"
            elif not item.get("is_active"):
                head = f"⚫ {head}"
            if item.get("deadline"):
                head += f" · ⏰ {_fmt_deadline(item['deadline'])}"

            with st.expander(head):
                with st.form(f"edit_{iid}"):
                    edited = _render_fields(itype, item, kp=f"e_{iid}")
                    is_active = st.toggle("Aktif", value=bool(item.get("is_active")), key=f"act_{iid}")
                    b1, b2 = st.columns(2)
                    save = b1.form_submit_button("💾 Simpan", type="primary")
                    delete = b2.form_submit_button("🗑 Hapus")

                    if save:
                        if not (edited.get("title") or "").strip():
                            st.error("Judul wajib diisi.")
                        else:
                            patch = {**edited, "is_active": bool(is_active)}
                            patch["title"] = patch["title"].strip()
                            patch["description"] = (patch.get("description") or "").strip() or None
                            try:
                                supabase.table("action_items").update(patch).eq(
                                    "id", iid
                                ).execute()
                                st.success("✅ Diperbarui.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Gagal simpan: {exc}")

                    if delete:
                        try:
                            supabase.table("action_items").delete().eq("id", iid).execute()
                            st.success("🗑 Dihapus.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Gagal hapus: {exc}")

                st.caption(f'pakai di WA: "ingetin {item.get("title")}"')
