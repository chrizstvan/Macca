"""Missions page — active list + create-mission form + brief broadcast."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import api, theme  # noqa: E402,F401 (theme auto-installs Plotly)
from utils.db import (  # noqa: E402
    clear_caches,
    get_missions,
    get_volunteers,
    supabase,
)

st.set_page_config(page_title="Missions — Macca", page_icon="📋", layout="wide")
st.title("📋 Manajemen Misi")


# --------------------------------------------------------------------------- #
# ACTIVE MISSIONS LIST                                                         #
# --------------------------------------------------------------------------- #


missions = get_missions()
if not missions:
    st.info("Belum ada misi. Buat misi baru di bawah.")
else:
    for mission in missions:
        status_dot = "🟢" if mission["status"] == "active" else "⚫"
        header = (
            f"{status_dot} {mission['title']} — "
            f"{mission['total_kg']:g}/{mission['target_kg']:g} kg "
            f"({mission['pct']}%)"
        )
        with st.expander(header):
            c1, c2, c3 = st.columns(3)
            c1.metric("Terkumpul", f"{mission['total_kg']:g} kg")
            c2.metric("Progress", f"{mission['pct']}%")
            c3.metric("Deadline", mission["deadline_label"])

            st.progress(min(mission["pct"] / 100, 1.0))

            if mission.get("description"):
                st.write(f"**Deskripsi:** {mission['description']}")
            st.write(f"**SOP:** {mission.get('sop') or '-'}")
            st.write(f"**Drop point:** {mission.get('drop_point') or '-'}")
            st.write(f"**Kontak darurat:** {mission.get('emergency_contact') or '-'}")
            if mission.get("avoid_items"):
                st.write(f"**Hindari:** {mission['avoid_items']}")
            if mission.get("field_tips"):
                st.write(f"**Tips lapangan:** {mission['field_tips']}")
            if mission.get("partner_contact"):
                st.write(f"**Kontak mitra:** {mission['partner_contact']}")

            if st.button("📨 Kirim Brief ke Semua", key=f"brief_{mission['id']}"):
                try:
                    result = api.send_mission_brief(str(mission["id"]))
                    st.success(
                        f"Brief dikirim ke {result.get('dispatched', '?')} "
                        "volunteer yang diassign!"
                    )
                except Exception as exc:
                    st.error(f"Gagal: {exc}")


# --------------------------------------------------------------------------- #
# CREATE MISSION FORM                                                          #
# --------------------------------------------------------------------------- #


st.divider()
st.subheader("➕ Buat Misi Baru")

PLASTIC_TYPE_CHOICES = (
    "PET (kode 1)", "HDPE (kode 2)", "PP (kode 5)",
    "LDPE (kode 4)", "Semua jenis",
)

with st.form("create_mission", clear_on_submit=True):
    title = st.text_input("Judul Misi *")
    description = st.text_area("Deskripsi & Tujuan")

    f1, f2 = st.columns(2)
    start_date = f1.date_input("Tanggal Mulai", dt.date.today())
    deadline = f2.date_input(
        "Deadline Laporan", dt.date.today() + dt.timedelta(days=14)
    )
    deadline_time = f2.time_input("Jam Deadline", dt.time(20, 0))

    f3, f4 = st.columns(2)
    target_kg = f3.number_input("Target Total (kg)", value=500, min_value=1)
    default_quota = f4.number_input(
        "Kuota Default per Volunteer (kg)", value=20, min_value=1
    )

    st.markdown("**SOP & Panduan Lapangan**")
    sop = st.text_area(
        "SOP Khusus Misi Ini",
        placeholder="Prioritaskan PET dan HDPE. Hindari styrofoam…",
    )
    plastic_types = st.multiselect("Jenis Plastik Prioritas", PLASTIC_TYPE_CHOICES)
    avoid_items = st.text_input(
        "Yang Harus Dihindari", placeholder="Styrofoam, plastik berminyak"
    )
    field_tips = st.text_area(
        "Tips Lapangan",
        placeholder="Koordinasi dengan RW dulu. Foto timbangan wajib…",
    )

    st.markdown("**Lokasi & Kontak**")
    drop_point = st.text_input("Titik Kumpul / Drop Point")
    emergency_contact = st.text_input("Kontak Darurat Lapangan")
    partner_contact = st.text_input("Kontak Mitra/Pengepul (opsional)")

    st.markdown("**Notifikasi Otomatis**")
    auto_brief = st.toggle(
        "Kirim brief ke volunteer saat misi dibuat", value=True
    )
    remind_days = st.selectbox("Reminder otomatis H-", (1, 2, 3))

    st.markdown("**Assign Volunteer**")
    vols_df = get_volunteers(active_only=True)
    vol_records = vols_df.to_dict("records") if not vols_df.empty else []
    selected_names = st.multiselect(
        "Pilih volunteer",
        options=[v.get("name") for v in vol_records if v.get("name")],
    )

    b1, b2 = st.columns(2)
    save_draft = b1.form_submit_button("💾 Simpan Draft")
    create_broadcast = b2.form_submit_button(
        "🚀 Buat & Broadcast", type="primary"
    )

    if save_draft or create_broadcast:
        if not title:
            st.error("Judul misi wajib diisi!")
        else:
            mission_data = {
                "title": title.strip(),
                "description": description.strip(),
                "start_date": start_date.isoformat(),
                "deadline": dt.datetime.combine(
                    deadline, deadline_time, tzinfo=dt.timezone.utc
                ).isoformat(),
                "target_kg": int(target_kg),
                "default_quota_kg": int(default_quota),
                "sop": sop.strip(),
                "plastic_types": plastic_types,
                "avoid_items": avoid_items.strip(),
                "field_tips": field_tips.strip(),
                "drop_point": drop_point.strip(),
                "emergency_contact": emergency_contact.strip(),
                "partner_contact": partner_contact.strip(),
                "reminder_days": int(remind_days),
                "status": "active" if create_broadcast else "draft",
            }
            mission_data = {k: v for k, v in mission_data.items() if v not in (None, "")}

            try:
                result = supabase.table("missions").insert(mission_data).execute()
            except Exception as exc:
                st.error(
                    f"Gagal simpan misi: {exc}\n\nPastikan schema "
                    "``missions`` punya kolom yang dipakai (sop, drop_point, "
                    "emergency_contact, target_kg, dll)."
                )
                result = None

            mission_row = (result.data or [{}])[0] if result else {}
            mission_id = mission_row.get("id")

            # Assignments — best-effort.
            if mission_id and selected_names:
                assignments = [
                    {
                        "volunteer_id": v["id"],
                        "mission_id": mission_id,
                        "quota_kg": int(default_quota),
                        "assigned_area": v.get("area") or "-",
                    }
                    for v in vol_records
                    if v.get("name") in selected_names
                ]
                if assignments:
                    try:
                        supabase.table("volunteer_missions").insert(assignments).execute()
                    except Exception as exc:
                        st.warning(f"Misi tersimpan, tapi assignment gagal: {exc}")

            # Auto-brief.
            if mission_id and create_broadcast and auto_brief:
                try:
                    api.send_mission_brief(str(mission_id))
                except Exception as exc:
                    st.warning(f"Brief gagal dikirim: {exc}")

            if mission_id:
                clear_caches()
                if create_broadcast:
                    st.success(
                        f"✅ Misi '{title}' dibuat! "
                        f"{len(selected_names)} volunteer di-assign."
                    )
                else:
                    st.success(f"💾 Draft '{title}' disimpan.")
                st.rerun()
