"""Election handler — per-team ketua/wakil election.

Iteration 1: start (with approval gate) + open nomination (blast to team).
Nomination collection, close/recap, voting, and result come in later iterations.

State machine (``elections.status``):
    draft → nomination_open → nomination_closed → voting_open → voting_closed → completed
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Matches "Nama (nomor)" / "Nama nomor" — captures name + Indonesian phone.
_NOMINATION_PATTERN = re.compile(
    r"(.+?)\s*\(?\s*(0\d{8,13}|\+?62\d{8,13})\s*\)?", re.DOTALL
)
_PHONE_ONLY = re.compile(r"(0\d{8,13}|\+?62\d{8,13})")

NOMINATION_BLAST = (
    "PEMILIHAN KETUA KELOMPOK - PENCALONAN\n\n"
    "Halo! Saatnya memilih ketua kelompok kita.\n\n"
    "Calonkan 1 orang yang menurutmu cocok jadi ketua.\n"
    "Format: Nama (nomor WA)\n"
    "Contoh: Budi Santoso (08123456789)\n\n"
    "Nomor WA penting untuk memastikan tidak tertukar kalau ada nama sama.\n"
    "Kamu boleh mencalonkan diri sendiri.\n\n"
    "PENTING: Kamu hanya bisa mencalonkan SATU KALI dan TIDAK BISA DIUBAH.\n"
    "Pikirkan baik-baik dulu sebelum mengirim ya!\n\n"
    "Kalau sudah yakin, balas pesan ini dengan nama calonmu."
)


async def _send_to_many(members: list[dict], text: str) -> dict:
    """DM ``text`` to every member; returns ``{"sent": n}``. Never raises."""
    from backend.agents.services.notifications import notify_volunteer

    sent = 0
    for v in members:
        try:
            await notify_volunteer(v, text)
            sent += 1
        except Exception as exc:  # noqa: BLE001 — one failure must not abort blast
            logger.warning("election blast to %s failed: %s", v.get("name"), exc)
    return {"sent": sent}


async def start_election_request(team_name: str, context: dict) -> str:
    """Fasilitator asks to start an election — reply with an approval gate."""
    from backend.infrastructure.composition_root import (
        build_election_repository,
        build_volunteer_query_repository,
    )

    existing = await build_election_repository().get_active(team_name)
    if existing:
        return (
            f"Sudah ada pemilihan aktif untuk {team_name} "
            f"(status: {existing['status']}). Lanjutkan yang itu ya."
        )

    members = await build_volunteer_query_repository().list_by_team(team_name)
    if not members:
        return f"Kelompok '{team_name}' tidak ditemukan atau kosong."

    return (
        f"Mau mulai PENCALONAN ketua untuk kelompok {team_name}?\n"
        f"Anggota: {len(members)} orang\n\n"
        "Kalau setuju, bot akan blast ke semua anggota:\n"
        "'Calonkan 1 nama ketua, format: Nama (nomor WA)'\n\n"
        f"Ketik 'ya mulai pencalonan {team_name}' untuk lanjut, atau 'batal'."
    )


async def open_nomination(team_name: str) -> str:
    """Fasilitator confirmed — create the election + blast nomination prompt."""
    from backend.infrastructure.composition_root import (
        build_election_repository,
        build_volunteer_query_repository,
    )

    election_repo = build_election_repository()
    existing = await election_repo.get_active(team_name)
    if existing:
        return (
            f"Sudah ada pemilihan aktif untuk {team_name} "
            f"(status: {existing['status']}). Nggak dibuka ulang ya."
        )

    members = await build_volunteer_query_repository().list_by_team(team_name)
    if not members:
        return f"Kelompok '{team_name}' tidak ditemukan atau kosong."

    await election_repo.create(team=team_name, status="nomination_open")
    result = await _send_to_many(members, NOMINATION_BLAST)

    return (
        f"Pencalonan kelompok {team_name} DIBUKA.\n"
        f"Blast terkirim ke {result['sent']} anggota.\n\n"
        "Volunteer sekarang bisa mencalonkan. Kalau sudah cukup, ketik "
        f"'tutup pencalonan {team_name}' untuk rekap."
    )


# --------------------------------------------------------------------------- #
# Nomination intake (volunteer → bot)                                          #
# --------------------------------------------------------------------------- #


def parse_nomination(text: str) -> tuple[str, str] | None:
    """Parse "Nama (nomor)" → (name, phone). None when no phone is found."""
    if not text:
        return None
    m = _NOMINATION_PATTERN.search(text.strip())
    if m:
        name = m.group(1).strip().rstrip("(").strip()
        phone = m.group(2).strip()
        if name and phone:
            return name, phone
    # Fallback: phone anywhere, name = the rest.
    m2 = _PHONE_ONLY.search(text)
    if m2:
        phone = m2.group(1)
        name = text.replace(phone, "").strip(" ()-\n")
        if name:
            return name, phone
    return None


async def try_handle_nomination(volunteer: dict, message: str) -> str | None:
    """Handle a volunteer's nomination when their team's election is open.

    Returns the reply text, or ``None`` to let normal routing continue (no open
    nomination for the volunteer's team).
    """
    from backend.infrastructure.composition_root import (
        build_election_repository,
        build_volunteer_query_repository,
    )
    from backend.utils.phone_utils import normalize_phone

    team = (volunteer.get("team") or "").strip()
    if not team:
        return None

    repo = build_election_repository()
    election = await repo.get_active(team)
    if not election or election.get("status") != "nomination_open":
        return None  # not a nomination context — continue normal routing

    parsed = parse_nomination(message)
    if not parsed:
        return (
            "Format pencalonan kurang tepat. Gunakan: Nama (nomor WA)\n"
            "Contoh: Budi Santoso (08123456789)"
        )
    candidate_name, candidate_phone = parsed
    candidate_phone = normalize_phone(candidate_phone) or candidate_phone

    # Locked — one nomination per volunteer.
    existing = await repo.get_nomination(
        election_id=election["id"], nominator_id=str(volunteer["id"])
    )
    if existing:
        return (
            f"Kamu sudah mencalonkan {existing.get('candidate_name')} "
            f"({existing.get('candidate_phone')}) sebelumnya.\n"
            "Pencalonan hanya bisa 1x dan tidak bisa diubah ya. Terima kasih!"
        )

    candidate_vol = await build_volunteer_query_repository().get_by_phone(
        candidate_phone
    )

    try:
        await repo.add_nomination(
            election_id=election["id"],
            nominator_id=str(volunteer["id"]),
            candidate_name=candidate_name,
            candidate_phone=candidate_phone,
            candidate_volunteer_id=(
                str(candidate_vol["id"]) if candidate_vol else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 — UNIQUE race → already nominated
        logger.warning("nomination insert failed (likely dup) for %s: %s", volunteer.get("name"), exc)
        return (
            "Kamu sudah mencalonkan sebelumnya. Pencalonan hanya bisa 1x ya. "
            "Terima kasih!"
        )

    return (
        f"Pencalonanmu tercatat: {candidate_name} ({candidate_phone})\n\n"
        "Terima kasih sudah ikut mencalonkan ketua kelompok! "
        "Ditunggu ya hasil pencalonannya. Semangat! 🌱"
    )


# --------------------------------------------------------------------------- #
# Close nomination — tally + report (fasilitator)                              #
# --------------------------------------------------------------------------- #


def _tally_nominations(nominations: list[dict]) -> list[dict]:
    """Group by candidate phone (fallback name); count; sort desc by votes."""
    buckets: dict[str, dict] = {}
    for n in nominations:
        phone = n.get("candidate_phone")
        key = phone or (n.get("candidate_name") or "").strip().lower()
        if key not in buckets:
            buckets[key] = {
                "candidate_phone": phone,
                "candidate_name": n.get("candidate_name") or "?",
                "votes": 0,
            }
        buckets[key]["votes"] += 1
    return sorted(buckets.values(), key=lambda c: c["votes"], reverse=True)


async def close_nomination(team_name: str) -> str:
    """Fasilitator closes nomination — tally, save top-3 finalists, report."""
    from backend.infrastructure.composition_root import build_election_repository

    repo = build_election_repository()
    election = await repo.get_active(team_name)
    if not election or election.get("status") != "nomination_open":
        return f"Tidak ada pencalonan aktif untuk {team_name}."

    await repo.update_status(election_id=election["id"], status="nomination_closed")

    nominations = await repo.list_nominations(election_id=election["id"])
    tally = _tally_nominations(nominations)
    if not tally:
        return f"Belum ada pencalonan masuk untuk {team_name}."

    top3 = tally[:3]

    tie_note = ""
    if len(tally) > 3 and tally[2]["votes"] == tally[3]["votes"]:
        tie_note = (
            f"\nCatatan: ada seri di posisi 3 ({tally[2]['votes']} suara). "
            "Fasilitator bisa tentukan siapa yang lolos, atau ambil semua yang seri."
        )

    for i, c in enumerate(top3):
        await repo.add_finalist(
            election_id=election["id"],
            candidate_phone=c["candidate_phone"],
            candidate_name=c["candidate_name"],
            nomination_count=c["votes"],
            slot_number=i + 1,
        )

    def _fmt(rows: list[dict]) -> str:
        return "\n".join(
            f"{i + 1}. {c['candidate_name']} ({c['candidate_phone'] or '-'}) "
            f"- {c['votes']} suara"
            for i, c in enumerate(rows)
        )

    return (
        f"REKAP PENCALONAN - Kelompok {team_name}\n\n"
        f"Hasil lengkap (urut suara terbanyak):\n{_fmt(tally)}"
        f"{tie_note}\n\n"
        f"3 KANDIDAT TERATAS yang akan maju ke voting:\n{_fmt(top3)}\n\n"
        f"Kalau setuju, ketik 'lanjut voting {team_name}' untuk mulai voting final.\n"
        "Kalau mau ubah kandidat, edit dulu di dashboard."
    )


# --------------------------------------------------------------------------- #
# Voting — open + intake                                                       #
# --------------------------------------------------------------------------- #


async def open_voting(team_name: str) -> str:
    """Fasilitator opens final voting — blast the 3 finalists to the team."""
    from backend.infrastructure.composition_root import (
        build_election_repository,
        build_volunteer_query_repository,
    )

    repo = build_election_repository()
    election = await repo.get_active(team_name)
    if not election or election.get("status") != "nomination_closed":
        return f"Pencalonan {team_name} belum ditutup atau tidak ada."

    finalists = await repo.get_finalists(election_id=election["id"])
    if not finalists:
        return f"Belum ada finalis untuk {team_name}."

    await repo.update_status(election_id=election["id"], status="voting_open")

    options = "\n".join(
        f"{f['slot_number']}. {f['candidate_name']} ({f.get('candidate_phone') or '-'})"
        for f in finalists
    )
    blast_msg = (
        "PEMILIHAN KETUA KELOMPOK - VOTING FINAL\n\n"
        "Ini dia 3 kandidat teratas hasil pencalonan!\n"
        "Pilih 1 yang menurutmu paling cocok jadi ketua:\n\n"
        f"{options}\n\n"
        "Balas dengan NOMOR pilihanmu (contoh: 1)\n"
        "Boleh pilih diri sendiri kalau kamu salah satu kandidat.\n\n"
        "PENTING: Kamu hanya bisa vote SATU KALI dan TIDAK BISA DIUBAH.\n"
        "Pikirkan baik-baik dulu sebelum mengirim ya!\n\n"
        "Ketua = suara terbanyak, Wakil = suara terbanyak kedua."
    )

    members = await build_volunteer_query_repository().list_by_team(team_name)
    result = await _send_to_many(members, blast_msg)

    return (
        f"Voting final kelompok {team_name} DIBUKA.\n"
        f"Blast terkirim ke {result['sent']} anggota.\n\n"
        f"Kalau sudah cukup, ketik 'tutup voting {team_name}' untuk hasil akhir."
    )


def parse_vote(text: str, finalists: list[dict]) -> dict | None:
    """Parse a vote — slot number (1/2/3) or candidate name — to a finalist."""
    t = (text or "").strip().lower()
    m = re.match(r"^\s*([123])\s*$", t)
    if m:
        slot = int(m.group(1))
        for f in finalists:
            if f.get("slot_number") == slot:
                return f
    for f in finalists:
        name = (f.get("candidate_name") or "").lower()
        if name and (name in t or t in name):
            return f
    return None


async def try_handle_vote(volunteer: dict, message: str) -> str | None:
    """Handle a volunteer's final vote when their team's voting is open."""
    from backend.infrastructure.composition_root import build_election_repository

    team = (volunteer.get("team") or "").strip()
    if not team:
        return None

    repo = build_election_repository()
    election = await repo.get_active(team)
    if not election or election.get("status") != "voting_open":
        return None  # not a voting context

    existing = await repo.get_vote(
        election_id=election["id"], voter_id=str(volunteer["id"])
    )
    if existing:
        return (
            f"Kamu sudah vote untuk {existing.get('candidate_name')} sebelumnya.\n"
            "Voting hanya bisa 1x dan tidak bisa diubah ya. Terima kasih!"
        )

    finalists = await repo.get_finalists(election_id=election["id"])
    choice = parse_vote(message, finalists)
    if not choice:
        opts = ", ".join(
            f"{f['slot_number']}={f['candidate_name']}" for f in finalists
        )
        return f"Pilihan kurang jelas. Balas dengan nomor: {opts}"

    try:
        await repo.add_vote(
            election_id=election["id"],
            voter_id=str(volunteer["id"]),
            candidate_phone=choice.get("candidate_phone"),
            candidate_name=choice["candidate_name"],
        )
    except Exception as exc:  # noqa: BLE001 — UNIQUE race → already voted
        logger.warning("vote insert failed (likely dup) for %s: %s", volunteer.get("name"), exc)
        return "Kamu sudah vote sebelumnya. Voting hanya bisa 1x ya. Terima kasih!"

    return (
        f"Vote kamu tercatat untuk: {choice['candidate_name']} ✅\n\n"
        "Terima kasih sudah ikut voting ketua kelompok! Suaramu sangat berarti. "
        "Ditunggu hasil akhirnya ya 🌱"
    )


# --------------------------------------------------------------------------- #
# Close voting → ketua/wakil, finalize, announce                               #
# --------------------------------------------------------------------------- #


def _fmt_tally(rows: list[dict]) -> str:
    return "\n".join(
        f"{i + 1}. {c['candidate_name']} ({c.get('candidate_phone') or '-'}) "
        f"- {c['votes']} suara"
        for i, c in enumerate(rows)
    )


async def close_voting(team_name: str) -> str:
    """Fasilitator closes voting — tally, determine ketua/wakil, report."""
    from backend.infrastructure.composition_root import build_election_repository

    repo = build_election_repository()
    election = await repo.get_active(team_name)
    if not election or election.get("status") != "voting_open":
        return f"Tidak ada voting aktif untuk {team_name}."

    await repo.update_status(election_id=election["id"], status="voting_closed")

    votes = await repo.list_votes(election_id=election["id"])
    tally = _tally_nominations(votes)  # same shape: candidate_phone/name → votes
    if not tally:
        return f"Belum ada vote masuk untuk {team_name}."

    ketua = tally[0]
    wakil = tally[1] if len(tally) > 1 else None

    tie_note = ""
    if len(tally) > 1 and tally[0]["votes"] == tally[1]["votes"]:
        tie_note = (
            "\nPERHATIAN: SERI di posisi teratas! "
            f"{tally[0]['candidate_name']} dan {tally[1]['candidate_name']} "
            f"sama-sama {tally[0]['votes']} suara. Fasilitator perlu tentukan "
            "ketua & wakil manual, atau voting ulang."
        )

    wakil_line = (
        f"WAKIL KETUA: {wakil['candidate_name']} ({wakil.get('candidate_phone') or '-'}) "
        f"- {wakil['votes']} suara"
        if wakil
        else "WAKIL KETUA: (tidak ada kandidat kedua)"
    )

    return (
        f"HASIL VOTING FINAL - Kelompok {team_name}\n\n"
        f"Hasil lengkap:\n{_fmt_tally(tally)}"
        f"{tie_note}\n\n"
        f"KETUA: {ketua['candidate_name']} ({ketua.get('candidate_phone') or '-'}) "
        f"- {ketua['votes']} suara\n"
        f"{wakil_line}\n\n"
        f"Kalau setuju, ketik 'sahkan hasil {team_name}' untuk finalisasi.\n"
        "Kalau mau ubah, edit di dashboard."
    )


async def finalize_election(team_name: str) -> str:
    """Fasilitator confirms result — persist ketua/wakil + status completed."""
    from backend.infrastructure.composition_root import build_election_repository

    repo = build_election_repository()
    election = await repo.get_active(team_name)
    if not election or election.get("status") != "voting_closed":
        return (
            f"Voting {team_name} belum ditutup. Ketik 'tutup voting {team_name}' dulu."
        )

    votes = await repo.list_votes(election_id=election["id"])
    tally = _tally_nominations(votes)
    if not tally:
        return f"Belum ada vote untuk {team_name}, tidak bisa disahkan."

    ketua = tally[0]
    wakil = tally[1] if len(tally) > 1 else None

    await repo.set_result(
        election_id=election["id"],
        ketua_name=ketua["candidate_name"],
        ketua_phone=ketua.get("candidate_phone"),
        wakil_name=wakil["candidate_name"] if wakil else None,
        wakil_phone=wakil.get("candidate_phone") if wakil else None,
        status="completed",
    )

    return (
        f"Hasil pemilihan kelompok {team_name} DISAHKAN. ✅\n"
        f"Ketua: {ketua['candidate_name']}\n"
        f"Wakil: {wakil['candidate_name'] if wakil else '-'}\n\n"
        f"Mau bot umumkan ke kelompok? Ketik 'umumkan hasil {team_name}'."
    )


async def announce_result(team_name: str) -> str:
    """Broadcast the finalized ketua/wakil to the team."""
    from backend.infrastructure.composition_root import (
        build_election_repository,
        build_volunteer_query_repository,
    )

    election = await build_election_repository().get_latest(team_name)
    if not election or election.get("status") != "completed" or not election.get("ketua_name"):
        return f"Belum ada hasil final untuk {team_name}. Sahkan dulu ya."

    wakil_line = (
        f"Wakil Ketua: {election['wakil_name']}"
        if election.get("wakil_name")
        else "Wakil Ketua: -"
    )
    announce = (
        f"HASIL PEMILIHAN KETUA KELOMPOK {team_name} 🎉\n\n"
        f"Ketua: {election['ketua_name']}\n"
        f"{wakil_line}\n\n"
        "Selamat kepada ketua & wakil terpilih! Terima kasih semua yang sudah "
        "ikut mencalonkan dan voting. Semangat berkegiatan bareng ya! 🌱"
    )

    members = await build_volunteer_query_repository().list_by_team(team_name)
    result = await _send_to_many(members, announce)
    return f"Pengumuman hasil kelompok {team_name} terkirim ke {result['sent']} anggota. 🎉"


# --------------------------------------------------------------------------- #
# Status                                                                       #
# --------------------------------------------------------------------------- #

_STATUS_LABEL = {
    "draft": "Belum mulai",
    "nomination_open": "Pencalonan DIBUKA",
    "nomination_closed": "Pencalonan ditutup (rekap)",
    "voting_open": "Voting DIBUKA",
    "voting_closed": "Voting ditutup (rekap)",
    "completed": "Selesai",
    "cancelled": "Dibatalkan",
}


async def show_election_status(team_name: str) -> str:
    """Report the current election phase + progress for a team."""
    from backend.infrastructure.composition_root import (
        build_election_repository,
        build_volunteer_query_repository,
    )

    repo = build_election_repository()
    election = await repo.get_latest(team_name)
    if not election:
        return f"Belum ada pemilihan untuk kelompok {team_name}."

    status = election.get("status")
    label = _STATUS_LABEL.get(status, status)
    total = len(await build_volunteer_query_repository().list_by_team(team_name))
    head = f"STATUS PEMILIHAN - Kelompok {team_name}\nStatus: {label}"

    if status == "nomination_open":
        noms = await repo.list_nominations(election_id=election["id"])
        voters = {n.get("nominator_volunteer_id") for n in noms}
        return f"{head}\nSudah mencalonkan: {len(voters)}/{total} anggota."
    if status == "nomination_closed":
        finalists = await repo.get_finalists(election_id=election["id"])
        lst = "\n".join(
            f"  {f['slot_number']}. {f['candidate_name']} - {f['nomination_count']} suara"
            for f in finalists
        )
        return f"{head}\n3 finalis:\n{lst}\n\nKetik 'lanjut voting {team_name}' untuk voting."
    if status == "voting_open":
        votes = await repo.list_votes(election_id=election["id"])
        voters = {v.get("voter_volunteer_id") for v in votes}
        return f"{head}\nSudah vote: {len(voters)}/{total} anggota."
    if status == "voting_closed":
        return f"{head}\nKetik 'sahkan hasil {team_name}' untuk finalisasi."
    if status == "completed":
        wakil = election.get("wakil_name") or "-"
        return f"{head}\nKetua: {election.get('ketua_name') or '-'}\nWakil: {wakil}"
    return head
