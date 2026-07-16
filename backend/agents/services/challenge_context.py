"""Active-challenge context block for volunteer/fasilitator guidance prompts.

Cross-cutting agent service: reads active ``action_items`` of type
``challenge`` (deadline not passed) and formats their ``description`` blob into
a system-prompt block so the bot can *guide* volunteers through the current
challenge. Scoring/submissions live outside the bot — the block explicitly
tells the model not to compute points.

Best-effort: any DB failure or absence of an active challenge yields an empty
string, so callers can unconditionally append the result.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_HEADER = (
    "=== CHALLENGE AKTIF SAAT INI ===\n"
    "Volunteer sedang mengikuti challenge di bawah ini. Kalau mereka bertanya "
    "atau minta bantuan soal challenge (tahapan, ide aksi, cara upload, "
    "hashtag/tag, deadline, format konten), pandu berdasarkan detail ini. "
    "JANGAN mengarang aturan, tanggal, atau hashtag yang tidak tertulis di "
    "sini. Kamu TIDAK menghitung skor — kalau ditanya soal nilai/poin, arahkan "
    "ke fasilitator atau gform.\n"
    "PENTING soal LOKASI/TEMPAT (mis. bank sampah): JANGAN PERNAH mengarang "
    "alamat, nama tempat, atau lokasi spesifik — kamu tidak punya data lokasi "
    "yang akurat. Kalau volunteer minta lokasi/tempat, PANDU cara survei "
    "sendiri: minta mereka buka Google Maps dan cari, mis. \"bank sampah "
    "[nama kecamatan/area]\", cek jam buka/kontak di Maps, lalu catat dan "
    "input hasilnya ke Google Form sesuai ketentuan challenge (pastikan belum "
    "terdaftar di sheet panitia). Bantu juga dengan tips survei, bukan alamat."
)


def _fmt_deadline(raw) -> str:
    """Render a deadline as ``YYYY-MM-DD HH:MM`` (drops seconds/timezone noise)."""
    s = str(raw)
    if ("T" in s or " " in s) and len(s) >= 16:
        return f"{s[:10]} {s[11:16]}"
    return s[:10]


def build_active_challenge_block() -> str:
    """Return the active-challenge system-prompt block, or ``""`` when none."""
    from backend.database.supabase_client import db
    from backend.utils.action_item_resolver import ActionItemResolver

    try:
        challenges = ActionItemResolver(db).list_active_challenges()
    except Exception as exc:  # noqa: BLE001 — guidance context is best-effort
        logger.warning("active challenge fetch failed: %s", exc)
        return ""
    if not challenges:
        return ""

    parts: list[str] = []
    for c in challenges:
        block = f"### {c.get('title') or '?'}"
        if c.get("deadline"):
            block += f"\nDeadline: {_fmt_deadline(c['deadline'])}"
        if c.get("reward"):
            block += f"\nHadiah/insentif: {c['reward']}"
        desc = (c.get("description") or "").strip()
        if desc:
            block += f"\n{desc}"
        parts.append(block)

    return _HEADER + "\n\n" + "\n\n".join(parts)
