"""APScheduler-backed task scheduler for periodic Macca jobs."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config import settings
from backend.database.supabase_client import db

logger = logging.getLogger(__name__)


class MaccaScheduler:
    """Thin wrapper around APScheduler's AsyncIOScheduler.

    Provides named helpers for the recurring jobs Macca needs (daily impact
    summaries, hourly escalation checks, etc.) and a generic interface for
    registering arbitrary coroutines on cron or interval triggers.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.start()
        logger.info("Macca scheduler started")

    def shutdown(self, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)
        logger.info("Macca scheduler stopped")

    def add_interval_job(
        self,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        job_id: str | None = None,
    ) -> str:
        """Register a coroutine to run on a fixed interval."""
        job = self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours),
            id=job_id,
            replace_existing=True,
        )
        logger.info("Scheduled interval job '%s' every %sh%sm%ss", job.id, hours, minutes, seconds)
        return job.id

    def add_cron_job(
        self,
        func: Callable,
        cron_expression: str,
        job_id: str | None = None,
        tz: str = "Asia/Jakarta",
    ) -> str:
        """Register a coroutine to run on a cron schedule (e.g. '0 9 * * *'), WIB by default."""
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError(f"Expected 5-part cron expression, got: {cron_expression!r}")

        minute, hour, day, month, day_of_week = parts
        job = self._scheduler.add_job(
            func,
            trigger=CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=tz,
            ),
            id=job_id,
            replace_existing=True,
        )
        logger.info("Scheduled cron job '%s' at '%s'", job.id, cron_expression)
        return job.id

    def remove_job(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)
        logger.info("Removed scheduled job '%s'", job_id)


# ------------------------------------------------------------------------- #
# Broadcast helpers                                                           #
# ------------------------------------------------------------------------- #


def get_all_active_volunteers() -> list[dict]:
    result = db.table("volunteers").select("*").eq("is_active", True).execute()
    return result.data or []


def get_mission_volunteers(mission_id: str) -> list[dict]:
    result = (
        db.table("volunteer_missions")
        .select("volunteers(*)")
        .eq("mission_id", mission_id)
        .execute()
    )
    return [row["volunteers"] for row in result.data or [] if row.get("volunteers")]


async def send_to_many(volunteers: list[dict], message: str, channel: str = "auto") -> int:
    """Broadcast a Markdown message to each volunteer's Telegram DM.

    `channel="auto"` currently always resolves to Telegram — the only live channel.
    Returns the number of successful sends.
    """
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    sent = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for volunteer in volunteers:
            chat_id = volunteer.get("telegram_id")
            if not chat_id:
                continue
            try:
                resp = await client.post(
                    url,
                    json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                )
                sent += resp.status_code == 200
            except Exception as exc:
                logger.error("Broadcast to %s failed: %s", chat_id, exc)
    logger.info("Broadcast delivered to %d/%d volunteers", sent, len(volunteers))
    return sent


# ------------------------------------------------------------------------- #
# Job 1 — weekly plastic fact (Monday 07:30 WIB)                              #
# ------------------------------------------------------------------------- #

PLASTIC_FACTS = [
    "Tahukah kamu? Hanya 9% dari seluruh plastik yang pernah diproduksi manusia berhasil didaur ulang. Sisanya di TPA, dibakar, atau di alam bebas 🌏",
    "Fakta mengejutkan: rata-rata kita menelan 5 gram mikroplastik per minggu — setara 1 kartu kredit plastik. Plastik yang kita buang sembarangan kembali ke tubuh kita 😱",
    "Indonesia adalah penghasil sampah plastik laut TERBESAR KE-2 di dunia. Tapi kita juga bisa jadi yang terdepan dalam perubahannya 💪",
    "Sebotol plastik PET yang kamu kumpulkan hari ini butuh 450 tahun untuk terurai di alam. Tapi di tangan recycler, bisa jadi benang, tas, atau botol baru dalam hitungan hari ♻️",
    "8 juta ton plastik masuk laut setiap tahun — setara menuang 1 truk sampah plastik ke laut setiap MENIT, 24 jam sehari, 365 hari setahun 🐠",
    "Styrofoam (PS/kode 6) adalah salah satu plastik paling berbahaya: tidak bisa didaur ulang, pecah menjadi jutaan serpihan kecil, dan mengandung benzena yang bisa picu kanker",
    "Plastik kode 1 (PET) dan kode 2 (HDPE) adalah yang paling bernilai untuk daur ulang. Botol-botol bening yang kamu kumpulkan bisa jadi pakaian, karpet, bahkan bangku taman 🪑",
]


async def send_weekly_plastic_fact() -> None:
    """Send 1 interesting plastic fact to all active volunteers."""
    week_num = datetime.now().isocalendar()[1]
    fact = PLASTIC_FACTS[week_num % len(PLASTIC_FACTS)]

    message = (
        f"🌱 *Fakta Plastik Minggu Ini*\n\n{fact}\n\n"
        "Terima kasih sudah jadi bagian dari perubahan! 💚"
    )

    volunteers = get_all_active_volunteers()
    await send_to_many(volunteers, message, channel="auto")


# ------------------------------------------------------------------------- #
# Job 2 — pre-mission education brief (triggered when a new mission starts)   #
# ------------------------------------------------------------------------- #

MISSION_EDUCATION_BRIEF = """📋 *Panduan Lapangan — Misi Baru Dimulai!*

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


async def send_mission_education_brief(mission_id: str) -> None:
    """Called when the fasilitator creates a new mission.

    Sends a practical field guide to all assigned volunteers.
    """
    volunteers = get_mission_volunteers(mission_id)
    await send_to_many(volunteers, MISSION_EDUCATION_BRIEF, channel="auto")


# ------------------------------------------------------------------------- #
# Job 4 — weekly quiz (Wednesday 12:00 WIB)                                   #
# ------------------------------------------------------------------------- #

QUIZZES = [
    {
        "question": "Plastik kode berapa yang PALING MUDAH dan PALING BERHARGA untuk didaur ulang?",
        "options": ["A) Kode 3 (PVC)", "B) Kode 1 (PET)", "C) Kode 6 (PS)", "D) Kode 7 (Other)"],
        "answer": "B",
        "explanation": "PET (kode 1) adalah plastik paling berharga untuk recycler — bisa dijadikan benang, pakaian, atau botol baru!",
    },
    {
        "question": "Berapa lama plastik biasa butuh untuk terurai di alam?",
        "options": ["A) 10–50 tahun", "B) 100–200 tahun", "C) 400–1000 tahun", "D) 5000 tahun"],
        "answer": "C",
        "explanation": "400–1000 tahun! Artinya plastik yang dibuang hari ini masih ada saat generasi ke-20 setelah kita.",
    },
    {
        "question": "Indonesia adalah penghasil sampah plastik laut terbesar ke berapa di dunia?",
        "options": ["A) Pertama", "B) Kedua", "C) Kelima", "D) Kesepuluh"],
        "answer": "B",
        "explanation": "Ke-2 setelah Tiongkok. Tapi dengan program seperti ini, kita bisa jadi yang terdepan dalam perubahannya! 💪",
    },
]


async def save_active_quiz(quiz: dict, expires_hours: int = 24) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    db.table("active_quizzes").insert(
        {
            "question": quiz["question"],
            "options": quiz["options"],
            "answer": quiz["answer"],
            "explanation": quiz["explanation"],
            "expires_at": expires_at.isoformat(),
        }
    ).execute()


def get_active_quiz() -> dict | None:
    """Return the most recent unexpired quiz, or None."""
    now = datetime.now(timezone.utc).isoformat()
    result = (
        db.table("active_quizzes")
        .select("*")
        .gt("expires_at", now)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


async def send_weekly_quiz() -> None:
    """Send a plastic knowledge quiz to all volunteers."""
    week_num = datetime.now().isocalendar()[1]
    quiz = QUIZZES[week_num % len(QUIZZES)]

    options = "\n".join(quiz["options"])
    message = (
        f"🧠 *Quiz Plastik Minggu Ini!*\n\n{quiz['question']}\n\n{options}\n\n"
        "Balas dengan huruf jawabanmu (A/B/C/D)!\n"
        "Jawaban benar dapat poin +10 🏆"
    )

    await save_active_quiz(quiz, expires_hours=24)

    volunteers = get_all_active_volunteers()
    await send_to_many(volunteers, message, channel="auto")


async def handle_quiz_answer(message: str, context: dict) -> str:
    """Check a volunteer's A/B/C/D reply against the active quiz and award points."""
    quiz = get_active_quiz()
    if quiz is None:
        return "Tidak ada quiz yang sedang aktif. Tunggu quiz berikutnya hari Rabu ya! 🧠"

    letter = message.strip().upper()
    correct_letter = quiz["answer"].strip().upper()

    if letter != correct_letter:
        return (
            f"❌ Belum tepat! Jawaban yang benar: *{correct_letter}*\n\n"
            f"💡 {quiz['explanation']}"
        )

    volunteer = context.get("volunteer")
    points_line = ""
    if volunteer:
        new_points = int(volunteer.get("points") or 0) + 10
        db.table("volunteers").update({"points": new_points}).eq(
            "id", volunteer["id"]
        ).execute()
        points_line = f"+10 poin! Total poinmu sekarang: {new_points} 🏆\n\n"

    return f"🎉 Benar! {points_line}💡 {quiz['explanation']}"
