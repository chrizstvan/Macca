"""Static content for proactive plastic-education jobs.

Pure data — no IO, no LLM, no DB. Kept in the application layer so use
cases that broadcast it don't have to know about presentation-specific
prompt files.
"""

from __future__ import annotations

from typing import TypedDict


# --------------------------------------------------------------------------- #
# Job 1 — Weekly plastic fact                                                  #
# --------------------------------------------------------------------------- #

WEEKLY_FACTS: tuple[str, ...] = (
    "Tahukah kamu? Hanya 9% dari seluruh plastik yang pernah diproduksi "
    "manusia berhasil didaur ulang. Sisanya di TPA, dibakar, atau di alam "
    "bebas 🌏",
    "Fakta mengejutkan: rata-rata kita menelan 5 gram mikroplastik per "
    "minggu — setara 1 kartu kredit plastik. Plastik yang kita buang "
    "sembarangan kembali ke tubuh kita 😱",
    "Indonesia adalah penghasil sampah plastik laut TERBESAR KE-2 di dunia. "
    "Tapi kita juga bisa jadi yang terdepan dalam perubahannya 💪",
    "Sebotol plastik PET yang kamu kumpulkan hari ini butuh 450 tahun untuk "
    "terurai di alam. Tapi di tangan recycler, bisa jadi benang, tas, atau "
    "botol baru dalam hitungan hari ♻️",
    "8 juta ton plastik masuk laut setiap tahun — setara menuang 1 truk "
    "sampah plastik ke laut setiap MENIT, 24 jam sehari, 365 hari setahun 🐠",
    "Styrofoam (PS/kode 6) adalah salah satu plastik paling berbahaya: "
    "tidak bisa didaur ulang, pecah menjadi jutaan serpihan kecil, dan "
    "mengandung benzena yang bisa picu kanker",
    "Plastik kode 1 (PET) dan kode 2 (HDPE) adalah yang paling bernilai "
    "untuk daur ulang. Botol-botol bening yang kamu kumpulkan bisa jadi "
    "pakaian, karpet, bahkan bangku taman 🪑",
)


def weekly_fact_for(iso_week: int) -> str:
    return WEEKLY_FACTS[iso_week % len(WEEKLY_FACTS)]


def format_weekly_fact_message(iso_week: int) -> str:
    fact = weekly_fact_for(iso_week)
    return (
        "🌱 *Fakta Plastik Minggu Ini*\n\n"
        f"{fact}\n\n"
        "Terima kasih sudah jadi bagian dari perubahan! 💚"
    )


# --------------------------------------------------------------------------- #
# Job 2 — Pre-mission education brief                                          #
# --------------------------------------------------------------------------- #

MISSION_EDUCATION_BRIEF: str = """📋 *Panduan Lapangan: Challenge Baru Dimulai!*

Sebelum turun ke lapangan, ini yang perlu kamu ingat:

*Plastik prioritas (paling berharga):*
🟢 PET (kode 1) — botol bening
🟢 HDPE (kode 2) — botol tebal/jerigen

*Yang perlu dihindari mengumpulkan:*
🔴 Styrofoam (kode 6) — sulit didaur ulang
🔴 Plastik kotor/berminyak — akan ditolak

*Tips lapangan:*
• Gepengkan botol → hemat ruang 5x lebih banyak
• Pisahkan dari sampah organik sejak awal
• Foto sebelum dan sesudah untuk dokumentasi

*Kalau warga tidak mau berpartisipasi:*
Coba katakan: _"Pak/Bu, ini untuk masa depan anak cucu kita. Saya hanya minta bantu pisahkan botol plastiknya saja."_

Semangat! Setiap kg yang terkumpul = ratusan botol diselamatkan 💪"""


# --------------------------------------------------------------------------- #
# Job 4 — Weekly quiz                                                          #
# --------------------------------------------------------------------------- #


class QuizSpec(TypedDict):
    question: str
    options: list[str]
    answer: str         # canonical single uppercase letter A-D
    explanation: str


WEEKLY_QUIZZES: tuple[QuizSpec, ...] = (
    {
        "question": (
            "Plastik kode berapa yang PALING MUDAH dan PALING BERHARGA untuk "
            "didaur ulang?"
        ),
        "options": [
            "A) Kode 3 (PVC)",
            "B) Kode 1 (PET)",
            "C) Kode 6 (PS)",
            "D) Kode 7 (Other)",
        ],
        "answer": "B",
        "explanation": (
            "PET (kode 1) adalah plastik paling berharga untuk recycler — "
            "bisa dijadikan benang, pakaian, atau botol baru!"
        ),
    },
    {
        "question": "Berapa lama plastik biasa butuh untuk terurai di alam?",
        "options": [
            "A) 10–50 tahun",
            "B) 100–200 tahun",
            "C) 400–1000 tahun",
            "D) 5000 tahun",
        ],
        "answer": "C",
        "explanation": (
            "400–1000 tahun! Artinya plastik yang dibuang hari ini masih ada "
            "saat generasi ke-20 setelah kita."
        ),
    },
    {
        "question": (
            "Indonesia adalah penghasil sampah plastik laut terbesar ke "
            "berapa di dunia?"
        ),
        "options": ["A) Pertama", "B) Kedua", "C) Kelima", "D) Kesepuluh"],
        "answer": "B",
        "explanation": (
            "Ke-2 setelah Tiongkok. Tapi dengan program seperti ini, kita "
            "bisa jadi yang terdepan dalam perubahannya! 💪"
        ),
    },
)

QUIZ_POINTS_CORRECT = 10
QUIZ_TTL_HOURS = 24


def quiz_for(iso_week: int) -> QuizSpec:
    return WEEKLY_QUIZZES[iso_week % len(WEEKLY_QUIZZES)]


def format_quiz_message(quiz: QuizSpec) -> str:
    options = "\n".join(quiz["options"])
    return (
        "🧠 *Quiz Plastik Minggu Ini!*\n\n"
        f"{quiz['question']}\n\n"
        f"{options}\n\n"
        "Balas dengan huruf jawabanmu (A/B/C/D)! 🌱"
    )
