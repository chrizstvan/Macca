"""Volunteers page — stats, table, add, CSV import, not-connected outreach."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402,F401 (auto-installs Plotly defaults)
from utils.db import (  # noqa: E402
    clear_caches,
    get_volunteers,
    normalize_phone,
    supabase,
)

st.set_page_config(page_title="Volunteers — Macca", page_icon="👥", layout="wide")
st.title("👥 Manajemen Volunteer")


# --------------------------------------------------------------------------- #
# STATS BAR                                                                    #
# --------------------------------------------------------------------------- #


df = get_volunteers()
if df.empty:
    st.info("Belum ada volunteer terdaftar.")
else:
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    df["_last_contact_dt"] = pd.to_datetime(
        df["last_contact_at"], errors="coerce", utc=True
    )
    connected_mask = df["whatsapp_connected"].fillna(False).astype(bool)
    recent_mask = df["_last_contact_dt"] >= seven_days_ago

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(df))
    c2.metric("Sudah Connect WA", int(connected_mask.sum()))
    c3.metric("Belum Connect", int((~connected_mask).sum()), delta_color="inverse")
    c4.metric("Aktif 7 Hari", int(recent_mask.sum()))


# --------------------------------------------------------------------------- #
# SEARCH & FILTER                                                              #
# --------------------------------------------------------------------------- #


st.divider()
col_search, col_filter = st.columns([2, 1])
search = col_search.text_input("🔍 Cari nama atau nomor HP")
areas = (
    ["Semua", *sorted(df["area"].dropna().unique().tolist())]
    if not df.empty
    else ["Semua"]
)
area_filter = col_filter.selectbox("Filter area", areas)

view = df.copy()
if search and not view.empty:
    needle = search.lower()
    view = view[
        view["name"].fillna("").str.lower().str.contains(needle)
        | view["phone"].fillna("").str.lower().str.contains(needle)
    ]
if area_filter != "Semua" and not view.empty:
    view = view[view["area"] == area_filter]

st.caption(f"{len(view)} dari {len(df)} volunteer")


# --------------------------------------------------------------------------- #
# VOLUNTEER TABLE  (inline-edit ``team``: empty = individual, filled = team)   #
# --------------------------------------------------------------------------- #


if not view.empty:
    st.caption(
        "💡 Kolom **Tim** bisa diedit langsung — kosongkan untuk **misi "
        "individu**, isi nama tim untuk **misi tim**. Klik 'Simpan perubahan "
        "tim' setelah edit."
    )

    edit_cols = [
        c
        for c in (
            "name", "phone", "area", "quota_kg",
            "team", "whatsapp_connected", "last_contact_at",
        )
        if c in view.columns
    ]
    editable_df = view[["id", *edit_cols]].reset_index(drop=True)
    # Ensure team is a string-like column so the data_editor renders an
    # empty cell as "" rather than NaN.
    editable_df["team"] = editable_df["team"].fillna("").astype(str)

    edited = st.data_editor(
        editable_df,
        column_config={
            "id": None,  # hide UUID
            "name": st.column_config.TextColumn("Nama", disabled=True),
            "phone": st.column_config.TextColumn("Nomor HP", disabled=True),
            "area": st.column_config.TextColumn("Area"),
            "quota_kg": st.column_config.NumberColumn("Kuota (kg)", min_value=1),
            "team": st.column_config.TextColumn(
                "Tim",
                help=(
                    "Kosongkan → volunteer dapat misi individu. "
                    "Isi nama tim → volunteer dapat misi tim."
                ),
            ),
            "whatsapp_connected": st.column_config.CheckboxColumn(
                "WA Connected", disabled=True
            ),
            "last_contact_at": st.column_config.DatetimeColumn(
                "Terakhir Chat", format="DD MMM YYYY · HH:mm", disabled=True
            ),
        },
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key="vol_table_editor",
    )

    # ---- Team helpers ------------------------------------------------- #
    distinct_teams = sorted(
        {t for t in editable_df["team"].tolist() if (t or "").strip()}
    )

    save_cols = st.columns([1, 2])
    if save_cols[0].button("💾 Simpan perubahan tim", type="primary", key="team_save_btn"):
        edits = 0
        errors: list[str] = []
        # Compare row-by-row against the unedited view; persist any column
        # the user actually changed (team / area / quota_kg).
        for orig_row, new_row in zip(
            editable_df.to_dict("records"), edited.to_dict("records")
        ):
            patch: dict = {}
            new_team = (new_row.get("team") or "").strip()
            orig_team = (orig_row.get("team") or "").strip()
            if new_team != orig_team:
                # Empty → individual mission; non-empty → team mission.
                patch["team"] = new_team if new_team else None
            if (new_row.get("area") or "") != (orig_row.get("area") or ""):
                patch["area"] = (new_row.get("area") or "").strip() or None
            if int(new_row.get("quota_kg") or 0) != int(orig_row.get("quota_kg") or 0):
                patch["quota_kg"] = int(new_row.get("quota_kg") or 0)
            if not patch:
                continue
            try:
                supabase.table("volunteers").update(patch).eq(
                    "id", new_row["id"]
                ).execute()
                edits += 1
            except Exception as exc:
                errors.append(f"{new_row.get('name')}: {exc}")
        if errors:
            st.error(
                f"{len(errors)} row gagal disimpan:\n"
                + "\n".join(errors)
            )
        if edits:
            clear_caches()
            st.success(f"✅ {edits} volunteer diperbarui.")
            st.rerun()
        if not edits and not errors:
            st.info("Tidak ada perubahan.")

    # ---- Bulk team operations ---------------------------------------- #
    with st.expander("🧑‍🤝‍🧑 Bulk: pindahkan / kosongkan tim"):
        bulk_names = st.multiselect(
            "Pilih volunteer",
            options=view["name"].dropna().tolist(),
            key="team_bulk_names",
        )
        target_team = st.text_input(
            "Tim tujuan (kosongkan untuk hapus tim → misi individu)",
            value="",
            key="team_bulk_target",
        )
        suggestion = st.selectbox(
            "Atau pilih tim yang sudah ada",
            options=["—", *distinct_teams],
            key="team_bulk_suggest",
        )
        if suggestion != "—" and not target_team.strip():
            target_team = suggestion

        bc1, bc2 = st.columns(2)
        if bc1.button("Terapkan ke yang dipilih", key="team_bulk_apply"):
            if not bulk_names:
                st.warning("Pilih minimal satu volunteer.")
            else:
                ids = view[view["name"].isin(bulk_names)]["id"].tolist()
                new_value = target_team.strip() or None
                try:
                    supabase.table("volunteers").update(
                        {"team": new_value}
                    ).in_("id", ids).execute()
                    clear_caches()
                    label = f"tim **{new_value}**" if new_value else "**tanpa tim** (misi individu)"
                    st.success(f"✅ {len(ids)} volunteer dipindahkan ke {label}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gagal: {exc}")

        if bc2.button("🗑 Hapus tim dari semua yang dipilih", key="team_bulk_clear"):
            if not bulk_names:
                st.warning("Pilih minimal satu volunteer.")
            else:
                ids = view[view["name"].isin(bulk_names)]["id"].tolist()
                try:
                    supabase.table("volunteers").update(
                        {"team": None}
                    ).in_("id", ids).execute()
                    clear_caches()
                    st.success(
                        f"✅ {len(ids)} volunteer kembali ke misi individu."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gagal: {exc}")


# --------------------------------------------------------------------------- #
# ADD VOLUNTEER FORM                                                           #
# --------------------------------------------------------------------------- #


with st.expander("➕ Tambah Volunteer Baru"):
    with st.form("add_volunteer", clear_on_submit=True):
        f1, f2 = st.columns(2)
        name = f1.text_input("Nama Lengkap *")
        phone = f2.text_input("Nomor HP *", placeholder="08123456789")
        f3, f4 = st.columns(2)
        area = f3.text_input("Area Tugas *", placeholder="Menteng")
        quota = f4.number_input("Kuota (kg)", value=20, min_value=1)
        team = st.text_input("Tim", placeholder="Nama1, Nama2, Nama3")
        telegram_id = st.text_input(
            "Telegram ID (opsional)",
            placeholder="cth. 123456789 — hanya jika volunteer pakai Telegram",
        )
        submitted = st.form_submit_button("Simpan Volunteer")

        if submitted:
            tg_raw = telegram_id.strip()
            if not name or not phone or not area:
                st.error("Nama, nomor HP, dan area wajib diisi!")
            elif tg_raw and not tg_raw.isdigit():
                st.error("Telegram ID harus berupa angka (atau kosongkan).")
            else:
                normalized = normalize_phone(phone)
                payload = {
                    "name": name.strip(),
                    "phone": normalized,
                    "area": area.strip(),
                    "quota_kg": int(quota),
                    "is_active": True,
                }
                if team.strip():
                    payload["team"] = team.strip()
                if tg_raw:
                    payload["telegram_id"] = int(tg_raw)
                try:
                    supabase.table("volunteers").insert(payload).execute()
                    clear_caches()
                    st.success(f"✅ {name} berhasil didaftarkan!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gagal simpan: {exc}")


# --------------------------------------------------------------------------- #
# CSV IMPORT                                                                   #
# --------------------------------------------------------------------------- #


CSV_TEMPLATE = (
    "name,phone,area,quota_kg,team,telegram_id\n"
    "Rizki Pratama,08123456789,Menteng,25,Tim Cikini,\n"
)

with st.expander("📥 Import dari CSV"):
    st.caption(
        "Kolom wajib: ``name``, ``phone``, ``area``. "
        "Opsional: ``quota_kg``, ``team``, ``telegram_id``. "
        "Phone akan dinormalisasi ke format ``62…``."
    )
    st.download_button(
        "Download template CSV",
        data=CSV_TEMPLATE,
        file_name="template_volunteer.csv",
        mime="text/csv",
    )
    uploaded = st.file_uploader("Upload CSV", type="csv")
    if uploaded is not None:
        import_df = pd.read_csv(uploaded)
        st.dataframe(import_df, use_container_width=True, hide_index=True)

        required = {"name", "phone", "area"}
        missing = required - set(import_df.columns)
        if missing:
            st.error(f"Kolom wajib hilang: {', '.join(sorted(missing))}")
        elif st.button("Konfirmasi Import", type="primary"):
            records = []
            for raw in import_df.to_dict("records"):
                row = {
                    "name": str(raw.get("name") or "").strip(),
                    "phone": normalize_phone(raw.get("phone")),
                    "area": str(raw.get("area") or "").strip(),
                    "is_active": True,
                }
                if raw.get("quota_kg") not in (None, ""):
                    try:
                        row["quota_kg"] = int(float(raw["quota_kg"]))
                    except (TypeError, ValueError):
                        pass
                team_val = (raw.get("team") or "").strip() if isinstance(raw.get("team"), str) else ""
                if team_val:
                    row["team"] = team_val
                tg_val = str(raw.get("telegram_id") or "").strip()
                # pandas may read the column as a float (e.g. "123.0").
                if tg_val.endswith(".0"):
                    tg_val = tg_val[:-2]
                if tg_val.isdigit():
                    row["telegram_id"] = int(tg_val)
                if row["name"] and row["phone"] and row["area"]:
                    records.append(row)
            if not records:
                st.error("Tidak ada baris valid setelah validasi.")
            else:
                try:
                    supabase.table("volunteers").insert(records).execute()
                    clear_caches()
                    st.success(f"✅ {len(records)} volunteer diimport!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Gagal import: {exc}")


# --------------------------------------------------------------------------- #
# NOT CONNECTED SECTION                                                        #
# --------------------------------------------------------------------------- #


if not df.empty:
    not_connected = df[~df["whatsapp_connected"].fillna(False).astype(bool)]
    if not not_connected.empty:
        st.divider()
        st.warning(
            f"⚠️ {len(not_connected)} volunteer belum chat ke bot WA"
        )
        st.dataframe(
            not_connected[["name", "phone", "area"]],
            hide_index=True,
            use_container_width=True,
        )

        if st.button("📋 Tampilkan Pesan Undangan"):
            msg = (
                "Halo! Silakan daftar ke bot program WA dengan kirim pesan "
                "'halo' ke nomor bot, atau ke Telegram: "
                "t.me/gbp_bot?start=gbp2026"
            )
            st.code(msg)
            st.info("Copy pesan di atas dan kirim ke volunteer yang belum connect.")
