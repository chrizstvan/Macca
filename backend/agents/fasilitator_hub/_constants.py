"""Module-level constants for the fasilitator hub: regex, prompts, keywords."""

import re

LEADERBOARD_KEYWORDS = ("ranking", "leaderboard", "peringkat", "rank")

# Action-item reminder flow (generate draft → approve → schedule). Matched on
# free-form text BEFORE intent classification so it isn't swallowed by the
# generic ``send_reminder`` progress-nudge path.
REMINDER_REQUEST_KEYWORDS = ("reminder", "ingetin", "ingatkan", "pengingat")

STRATEGY_KEYWORDS = (
    "strategi", "saran", "ide", "gimana cara", "bagaimana cara",
    "pendapat", "rekomendasi", "menurut kamu", "menurut mu",
    "menurutmu", "menurut anda",
)

AT_RISK_KEYWORDS = (
    "berhenti", "nyerah", "menyerah", "mundur", "capek banget",
    "bosen", "mau keluar", "lelah sekali",
)

PROJECT_CONTEXT_PATTERNS = (
    re.compile(r"project\s+kita\s+ini\s+adalah\s+(.+)", re.IGNORECASE | re.DOTALL),
    re.compile(r"konteks\s+project\s+(?:kita\s+)?adalah\s+(.+)", re.IGNORECASE | re.DOTALL),
    re.compile(r"deskripsi\s+project\s+adalah\s+(.+)", re.IGNORECASE | re.DOTALL),
)

# /qa [phone:] question  — fasilitator forwards a question for an answer.
QA_PATTERN = re.compile(
    r"^/qa(?:\s+(\d{6,15})\s*:)?\s*(.+)?$",
    re.IGNORECASE | re.DOTALL,
)
# /send PHONE: text  — fasilitator instructs the bot to DM a volunteer.
SEND_PATTERN = re.compile(
    r"^/send(?:\s+(\d{6,15})\s*:\s*(.+))?$",
    re.IGNORECASE | re.DOTALL,
)

PSYCH_KEYWORDS = (
    "handle", "semangat", "semangatin", "nyerah", "menyerah",
    "berhenti", "mundur", "keluar", "capek", "ga lapor",
    "tidak lapor", "lelah", "hopeless",
)

DRAFT_PATTERN = re.compile(
    r"\b(?:draftkan|drafkan|draft|buatkan|buat)\s+(?:pesan\s+)?(?:untuk\s+)?([A-Za-z][\w'.-]+(?:\s+[A-Za-z][\w'.-]+)?)",
    re.IGNORECASE,
)

# Natural-language invite/send: "undang Sari", "ajak Budi", "invite Rina",
# "kirim undangan untuk Rina" → draft + confirm + WhatsApp send.
# Distinct from DRAFT_PATTERN (draft-only): these verbs mean "actually send".
INVITE_PATTERN = re.compile(
    r"\b(?:undang|ajak|invite|kirim(?:kan)?)\s+"
    r"(?:pesan\s+|undangan\s+|invitation\s+)?"
    r"(?:untuk\s+|kepada\s+|ke\s+)?"
    r"([A-Za-z][\w'.-]+(?:\s+[A-Za-z][\w'.-]+)?)",
    re.IGNORECASE,
)

QA_SYSTEM_PROMPT = (
    "Kamu adalah asisten edukasi untuk program pengumpulan plastik di Indonesia. "
    "Jawab pertanyaan volunteer dengan ringkas (maksimum 4 kalimat), akurat, dan "
    "mudah dipahami. Fokus topik: jenis plastik (kode 1-7), daur ulang, dampak "
    "lingkungan, SOP program. Bahasa Indonesia santai tapi informatif. Jangan "
    "tambahkan salam atau penutup — keluarkan jawabannya saja, siap di-copy "
    "fasilitator dan diteruskan ke volunteer."
)

# --------------------------------------------------------------------------- #
# Phase 6 — command classifier + suggestion engine                              #
# --------------------------------------------------------------------------- #

FAS_INTENTS: tuple[str, ...] = (
    "send_reminder",
    "get_status",
    "get_analytics",
    "create_mission",
    "assign_volunteer",
    "broadcast",
    "flag_review",
    "generate_report",
    "generate_content",
    "get_volunteer_detail",
    "query_other_volunteer",
    "save_report_for",
    "default",
)

INTENT_CLASSIFY_PROMPT = (
    "Klasifikasikan perintah fasilitator ke TEPAT SATU kategori berikut. "
    "Balas HANYA dengan nama kategorinya (snake_case), tanpa penjelasan.\n\n"
    "Kategori:\n"
    "- send_reminder: kirim reminder, ingatkan, remind volunteer\n"
    "- get_status: status program, siapa belum lapor, laporan hari ini, "
    "summary harian\n"
    "- get_analytics: analitik, statistik, grafik, tren, dampak total\n"
    "- create_mission: buat misi baru, tugas baru, tambah mission\n"
    "- assign_volunteer: assign volunteer, tugaskan, pindahkan ke area\n"
    "- broadcast: broadcast ke semua, umumkan ke semua volunteer\n"
    "- flag_review: cek laporan mencurigakan, review flag, approve/reject\n"
    "- generate_report: buat laporan sponsor/pemerintah/publik\n"
    "- generate_content: buat caption/konten/postingan sosmed\n"
    "- get_volunteer_detail: detail / profil / info volunteer tertentu\n"
    "- query_other_volunteer: tanya progres / tugas / status volunteer lain "
    "(misal 'apa tugas Rizki', 'Sari sudah lapor?', 'progress Hendra')\n"
    "- save_report_for: simpan/catat laporan atas nama volunteer lain "
    "(misal 'Sari: 5 kg Menteng', 'catat 3kg untuk Hendra di Cikini', "
    "'Rizki lapor 7kg dari Tebet hari ini')\n"
    "- default: pertanyaan strategis, konsultasi, atau tidak ada di atas\n\n"
    "Contoh:\n"
    "'kirim reminder ke semua yang belum lapor' → send_reminder\n"
    "'siapa belum lapor hari ini?' → get_status\n"
    "'tampilkan tren mingguan' → get_analytics\n"
    "'buat misi baru pengumpulan PET di Cikini' → create_mission\n"
    "'tugaskan Budi ke area Menteng' → assign_volunteer\n"
    "'umumkan ke semua: besok kumpul jam 8' → broadcast\n"
    "'cek laporan yang flagged' → flag_review\n"
    "'buatkan laporan dampak untuk donor' → generate_report\n"
    "'buat caption instagram dampak hari ini' → generate_content\n"
    "'detail volunteer Hendra' → get_volunteer_detail\n"
    "'apa tugas Rizki minggu ini?' → query_other_volunteer\n"
    "'Sari: 5 kg Menteng' → save_report_for\n"
    "'catat 3kg untuk Hendra di Cikini' → save_report_for\n"
    "'menurut kamu strategi terbaik untuk volunteer pasif?' → default"
)

SUGGESTIONS: dict[str, tuple[str, ...]] = {
    "send_reminder": (
        "Cek siapa sudah respon",
        "Kirim reminder bertarget tertentu",
        "Lihat status program",
    ),
    "get_status": (
        "Kirim reminder ke yang belum lapor",
        "Lihat detail volunteer tertentu",
        "Cek laporan flagged",
    ),
    "get_analytics": (
        "Buat laporan untuk donor",
        "Generate konten dari data ini",
        "Lihat ranking volunteer",
    ),
    "create_mission": (
        "Assign volunteer ke misi ini",
        "Broadcast pengumuman misi baru",
        "Cek semua misi aktif",
    ),
    "assign_volunteer": (
        "Lihat status assignment",
        "Broadcast informasi tugas",
        "Cek progress volunteer terkait",
    ),
    "broadcast": (
        "Cek delivery broadcast",
        "Buat reminder follow-up",
        "Lihat siapa sudah balas",
    ),
    "flag_review": (
        "Setujui semua",
        "Tolak laporan ini",
        "Lihat detail volunteer terkait",
    ),
    "generate_report": (
        "Kirim ke stakeholder",
        "Buat versi platform lain",
        "Generate konten media sosial",
    ),
    "generate_content": (
        "Buat versi platform lain",
        "Cek dampak hari ini",
        "Draft pesan reminder",
    ),
    "get_volunteer_detail": (
        "Kirim pesan personal",
        "Draft reminder untuk dia",
        "Cek seluruh tim",
    ),
    "query_other_volunteer": (
        "Kirim reminder",
        "Cek detail lengkap",
        "Lihat ranking",
    ),
    "save_report_for": (
        "Catat laporan volunteer lain",
        "Lihat status hari ini",
        "Cek laporan flagged",
    ),
    "default": (
        "Cek status program",
        "Lihat siapa belum lapor",
        "Generate konten harian",
    ),
}


REMIND_PATTERN = re.compile(
    r"^/remind(?:\s+(hadir|form|misi|progress))?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

REMIND_TEMPLATES: dict[str, str] = {
    "hadir": "Hai {name}! 📅 Jangan lupa hadir di kegiatan ya: {arg}",
    "form": "Hai {name}! 📋 Mohon isi form: {arg}",
    "misi": "Hai {name}! 🎯 Update misi: target {quota_kg:g} kg di {area}.",
    "progress": (
        "Hei {name}! 💪 Progress kamu {reported_kg:g}/{quota_kg:g} kg. "
        "Ayo semangat lapor ya!"
    ),
    "custom": "Hai {name}! {arg}",
}
