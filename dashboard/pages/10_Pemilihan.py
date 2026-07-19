"""Pemilihan page — drive the per-team election from the dashboard.

Buttons call the SAME backend functions as the WA commands (via
``/admin/elections/action``). Dashboard + WA are two doors to one flow; no
election logic is duplicated here. Reads (progress, tallies) hit Supabase
directly for a live view.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import api, theme  # noqa: E402,F401 (theme auto-installs Plotly)
from utils.db import supabase  # noqa: E402

st.set_page_config(page_title="Pemilihan — Macca", page_icon="🗳️", layout="wide")
st.title("🗳️ Pemilihan Ketua & Wakil Kelompok")

STATUS_LABEL = {
    "draft": "Belum mulai",
    "nomination_open": "Pencalonan dibuka",
    "nomination_closed": "Pencalonan ditutup (rekap)",
    "voting_open": "Voting dibuka",
    "voting_closed": "Voting ditutup (rekap)",
    "completed": "Selesai",
}


def _do(action: str, team: str, ok_msg: str) -> None:
    """Call the backend election action, surface its message, rerun."""
    try:
        res = api.election_action(team, action)
        st.success(res.get("message") or ok_msg)
        st.rerun()
    except Exception as exc:  # noqa: BLE001 — show API error to fasilitator
        st.error(f"Gagal: {exc}")


# --------------------------------------------------------------------------- #
# Pilih kelompok                                                              #
# --------------------------------------------------------------------------- #

teams = supabase.table("volunteers").select("team").execute().data or []
team_list = sorted({v["team"] for v in teams if v.get("team")})
if not team_list:
    st.warning("Belum ada kelompok (field `team`) pada volunteer.")
    st.stop()

selected_team = st.selectbox("Pilih Kelompok", team_list)

rows = (
    supabase.table("elections")
    .select("*")
    .eq("team", selected_team)
    .neq("status", "cancelled")
    .order("created_at", desc=True)
    .limit(1)
    .execute()
    .data
    or []
)
election = rows[0] if rows else None

if election:
    st.info(f"Status: {STATUS_LABEL.get(election['status'], election['status'])}")
else:
    st.warning("Belum ada pemilihan untuk kelompok ini.")

col1, col2 = st.columns(2)


def _members() -> list[dict]:
    return (
        supabase.table("volunteers")
        .select("id,name,phone")
        .eq("team", selected_team)
        .eq("is_active", True)
        .execute()
        .data
        or []
    )


def _progress_report(done_ids: set, label: str) -> None:
    members = _members()
    sudah = [m for m in members if m["id"] in done_ids]
    belum = [m for m in members if m["id"] not in done_ids]
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Sudah {label}", len(sudah))
    c2.metric("Belum", len(belum))
    c3.metric("Total anggota", len(members))
    st.progress(len(sudah) / len(members) if members else 0)
    with st.expander(f"Belum {label} ({len(belum)})"):
        for m in belum:
            st.write(f"- {m['name']} ({m.get('phone') or '-'})")
    with st.expander(f"Sudah {label} ({len(sudah)})"):
        for m in sudah:
            st.write(f"- {m['name']}")


# --------------------------------------------------------------------------- #
# Kontrol per state (mirror WA commands via backend)                          #
# --------------------------------------------------------------------------- #

if not election or election["status"] == "draft":
    if col1.button("Mulai Pencalonan", type="primary"):
        _do("open_nomination", selected_team, "Pencalonan dibuka & blast terkirim.")

elif election["status"] == "nomination_open":
    noms = (
        supabase.table("election_nominations")
        .select("nominator_volunteer_id,candidate_name,candidate_phone")
        .eq("election_id", election["id"])
        .execute()
        .data
        or []
    )
    _progress_report({n["nominator_volunteer_id"] for n in noms}, "mencalonkan")

    if noms:
        name_by_id = {m["id"]: m["name"] for m in _members()}

        # Detail: siapa mencalonkan siapa (nominasi TIDAK rahasia)
        st.subheader("Detail Pencalonan")
        st.dataframe(
            [
                {
                    "Pencalon": name_by_id.get(n["nominator_volunteer_id"], "?"),
                    "Mencalonkan": n.get("candidate_name") or "-",
                    "Nomor": n.get("candidate_phone") or "-",
                }
                for n in noms
            ],
            hide_index=True,
            use_container_width=True,
        )

        # Perolehan sementara (group by nomor kandidat)
        buckets: dict[str, dict] = {}
        for n in noms:
            key = n.get("candidate_phone") or (n.get("candidate_name") or "").lower()
            b = buckets.setdefault(
                key,
                {"name": n.get("candidate_name"), "phone": n.get("candidate_phone"), "count": 0},
            )
            b["count"] += 1
        ranking = sorted(buckets.values(), key=lambda c: c["count"], reverse=True)
        st.subheader("Perolehan Sementara")
        st.dataframe(
            [
                {"Kandidat": c["name"], "Nomor": c["phone"] or "-", "Suara": c["count"]}
                for c in ranking
            ],
            hide_index=True,
            use_container_width=True,
        )

    if col1.button("Tutup Pencalonan & Rekap"):
        _do("close_nomination", selected_team, "Pencalonan ditutup.")
    if col2.button("🔁 Resend ke yang belum mencalonkan"):
        _do("resend", selected_team, "Resend terkirim.")

elif election["status"] == "nomination_closed":
    finalists = (
        supabase.table("election_finalists")
        .select("*")
        .eq("election_id", election["id"])
        .order("slot_number")
        .execute()
        .data
        or []
    )
    st.subheader("3 Kandidat Teratas")
    for f in finalists:
        st.write(
            f"{f['slot_number']}. {f['candidate_name']} "
            f"({f.get('candidate_phone') or '-'}) - {f['nomination_count']} suara"
        )
    st.caption("Edit finalis di tabel `election_finalists` kalau perlu (opsional).")
    if col1.button("Lanjut Voting", type="primary"):
        _do("open_voting", selected_team, "Voting dibuka & blast terkirim.")

elif election["status"] == "voting_open":
    votes = (
        supabase.table("election_votes")
        .select("voter_volunteer_id")
        .eq("election_id", election["id"])
        .execute()
        .data
        or []
    )
    _progress_report({v["voter_volunteer_id"] for v in votes}, "vote")
    st.caption(
        "Catatan: siapa memilih siapa TIDAK ditampilkan (vote rahasia). "
        "Yang terlihat hanya SIAPA yang sudah/belum vote."
    )
    if col1.button("Tutup Voting & Hasil"):
        _do("close_voting", selected_team, "Voting ditutup.")
    if col2.button("🔁 Resend ke yang belum vote"):
        _do("resend", selected_team, "Resend terkirim.")

elif election["status"] == "voting_closed":
    votes = (
        supabase.table("election_votes")
        .select("candidate_phone,candidate_name")
        .eq("election_id", election["id"])
        .execute()
        .data
        or []
    )
    buckets: dict[str, dict] = {}
    for v in votes:
        key = v.get("candidate_phone") or (v.get("candidate_name") or "").lower()
        b = buckets.setdefault(
            key,
            {"name": v.get("candidate_name"), "phone": v.get("candidate_phone"), "votes": 0},
        )
        b["votes"] += 1
    tally = sorted(buckets.values(), key=lambda c: c["votes"], reverse=True)
    st.subheader("Hasil Voting")
    for i, c in enumerate(tally):
        st.write(f"{i + 1}. {c['name']} ({c['phone'] or '-'}) - {c['votes']} suara")
    if len(tally) > 1 and tally[0]["votes"] == tally[1]["votes"]:
        st.warning("⚠️ SERI di posisi teratas — tentukan manual / voting ulang.")
    if col1.button("Sahkan Hasil", type="primary"):
        _do("finalize", selected_team, "Hasil disahkan.")

elif election["status"] == "completed":
    st.success(f"🏆 KETUA: {election.get('ketua_name') or '-'}")
    st.success(f"🤝 WAKIL: {election.get('wakil_name') or '-'}")
    if col1.button("📢 Umumkan ke Kelompok"):
        _do("announce", selected_team, "Pengumuman terkirim.")

# Batalkan — direct status flip (semua state kecuali completed)
if election and election["status"] != "completed":
    st.divider()
    if st.button("Batalkan Pemilihan", type="secondary"):
        try:
            supabase.table("elections").update({"status": "cancelled"}).eq(
                "id", election["id"]
            ).execute()
            st.success("Pemilihan dibatalkan.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Gagal batal: {exc}")
