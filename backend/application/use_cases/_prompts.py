"""Prompts owned by the application layer (use cases).

Kept separate from ``backend.agents.prompts`` so use cases don't have to
import presentation-layer strings; agents that still need these strings
can re-export from here.
"""

from backend.knowledge.buku_saku_knowledge import BUKU_SAKU_GBP

# Program knowledge (jadwal kelas, deadline, link, poin, sertifikat) so the
# mission/challenge briefing can answer factual program questions.
BUKU_SAKU_SECTION = (
    "=== PENGETAHUAN PROGRAM (dari Buku Saku Relawan) ===\n"
    f"{BUKU_SAKU_GBP}\n\n"
    "Gunakan info ini untuk menjawab pertanyaan program (jadwal kelas, "
    "deadline, link, cara ikut challenge, poin, sertifikat). Kalau jawaban "
    "TIDAK ada di buku saku, jujur bilang tidak tahu dan arahkan ke "
    "fasilitator. Jangan mengarang."
)

BASE_BRIEFING_PROMPT = (
    "Kamu adalah asisten challenge untuk Chris-Fasil-GBP, platform koordinasi volunteer "
    "Generasi Bebas Plastik. "
    "Tugasmu menjawab pertanyaan volunteer tentang challenge, tugas, area, deadline, "
    "dan SOP berdasarkan data di bawah. "
    "Program berbasis CHALLENGE (aksi + konten media sosial). JANGAN pernah pakai "
    "kata 'misi' — selalu sebut 'challenge'. JANGAN menyebut kuota kg, target kg, "
    "poin, atau progres kg. "
    "Jawab dalam Bahasa Indonesia yang ramah, singkat, jelas, dan memotivasi. "
    "Jika data tidak tersedia, katakan dengan jujur dan sarankan menghubungi fasilitator. "
    "Format jawaban untuk Telegram (boleh pakai <b>bold</b> dan emoji secukupnya)."
)

SOP_SECTION = """SOP Program (berbasis Challenge):
1. Ikuti challenge yang sedang aktif (lihat detail challenge di atas kalau ada).
2. Lakukan aksi sesuai tahapan challenge.
3. Dokumentasikan aksimu (foto/video).
4. Unggah ke media sosial sesuai ketentuan (hashtag + tag wajib) dan isi Google Form jika diminta.
5. Perhatikan deadline challenge.
Kalau bingung soal tahapan atau cara unggah, tanya saja ke aku atau fasilitator."""

# User-facing reply strings used when domain rules short-circuit the LLM.
QUOTA_REACHED_MSG = (
    "Kamu sudah 2x tanya tentang challenge hari ini 😊 "
    "Untuk info lengkap silakan buka panduan program ya!"
)

LAST_FREE_NOTICE = (
    "\n\nIni adalah info challenge terakhir yang bisa aku berikan hari ini. "
    "Kalau masih ada pertanyaan, cek panduan program ya! 📖"
)

NOT_REGISTERED_MSG = (
    "Kamu belum terdaftar sebagai volunteer. "
    "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
)

NO_ACTIVE_MISSION_HINT = (
    "Challenge: arahkan volunteer untuk ikut challenge yang sedang aktif "
    "(lihat detail challenge di atas kalau ada). Kalau belum ada challenge "
    "aktif, bilang fasilitator akan menginformasikan challenge berikutnya. "
    "Jangan pakai kata 'misi'."
)
