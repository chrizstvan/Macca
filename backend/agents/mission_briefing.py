"""Mission briefing agent: answers questions about mission, area, quota, deadline, and SOP."""

import logging
from datetime import datetime, timezone

from .base_agent import BaseAgent
from backend.database.supabase_client import db

logger = logging.getLogger(__name__)

SOP_SECTION = """SOP Pengumpulan Plastik:
1. Kumpulkan plastik di area yang ditugaskan
2. Pilah berdasarkan jenis: PET (botol bening), HDPE (botol tebal/jerigen), PP (wadah makanan)
3. Timbang total plastik yang terkumpul
4. Foto plastik beserta timbangan sebagai bukti
5. Kirim laporan dengan format: "Laporan [berat] kg [lokasi]" disertai foto
6. Deadline laporan sesuai misi yang aktif

Tips pilah plastik:
- PET (kode 1): botol minuman bening, paling umum
- HDPE (kode 2): jerigen, botol sampo, lebih tebal dan buram
- PP (kode 5): wadah makanan, sedotan
- Lihat kode segitiga di bawah kemasan untuk memastikan"""

BASE_PROMPT = (
    "Kamu adalah asisten briefing misi untuk Macca, platform koordinasi volunteer "
    "pengumpulan sampah plastik (Generasi Bebas Plastik). "
    "Tugasmu menjawab pertanyaan volunteer tentang tugas, misi, area, kuota, deadline, "
    "dan SOP berdasarkan data di bawah. "
    "Jawab dalam Bahasa Indonesia yang ramah, singkat, jelas, dan memotivasi. "
    "Jika data tidak tersedia, katakan dengan jujur dan sarankan menghubungi fasilitator. "
    "Format jawaban untuk Telegram (boleh pakai <b>bold</b> dan emoji secukupnya)."
)


class MissionBriefingAgent(BaseAgent):
    """Briefs volunteers on their mission, area, quota, deadline, progress, and SOP."""

    def __init__(self) -> None:
        super().__init__(
            name="mission_briefing",
            description="Answers questions about mission, task, area, quota, deadline, and SOP",
        )

    async def process(self, message: str, context: dict) -> str:
        """Answer a mission/SOP question with full volunteer + mission context."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        # 2. Volunteer profile (already loaded by the router/handler)
        if volunteer is None:
            volunteer = context.get("volunteer")
        if volunteer is None:
            return (
                "Kamu belum terdaftar sebagai volunteer. "
                "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
            )

        # 1. Active mission from volunteer_missions + missions
        mission, assignment = self._get_active_mission(volunteer["id"])
        progress_kg = self._get_progress_kg(
            volunteer["id"], mission["id"] if mission else None
        )

        # 3. Rich system prompt with profile, mission, progress, and SOP
        system_prompt = self._build_system_prompt(volunteer, mission, assignment, progress_kg)

        # 4. Claude Haiku with last 10 chat messages + current message
        history = await self.get_chat_history(telegram_id, limit=10) if telegram_id else []
        messages = history + [{"role": "user", "content": message}]
        response = await self.call_claude(system_prompt, messages)

        # 5. Persist both sides of the exchange
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", response, self.name)

        # 6. Return the response
        return response

    def _get_active_mission(self, volunteer_id: str) -> tuple[dict | None, dict | None]:
        """Return (mission, assignment) for the volunteer's active mission, if any."""
        result = (
            db.table("volunteer_missions")
            .select("quota_kg, assigned_area, missions(*)")
            .eq("volunteer_id", volunteer_id)
            .execute()
        )
        for row in result.data or []:
            mission = row.get("missions")
            if mission and mission.get("status") == "active":
                return mission, row
        return None, None

    def _get_progress_kg(self, volunteer_id: str, mission_id: str | None) -> float:
        """Sum of kg reported by this volunteer (scoped to the mission when known)."""
        query = db.table("reports").select("kg_collected").eq("volunteer_id", volunteer_id)
        if mission_id:
            query = query.eq("mission_id", mission_id)
        result = query.execute()
        return sum(float(r["kg_collected"]) for r in result.data or [])

    def _build_system_prompt(
        self,
        volunteer: dict,
        mission: dict | None,
        assignment: dict | None,
        progress_kg: float,
    ) -> str:
        team = volunteer.get("team") or []
        quota = (assignment or {}).get("quota_kg") or volunteer.get("quota_kg") or 0
        area = (assignment or {}).get("assigned_area") or volunteer.get("area") or "-"

        volunteer_section = (
            f"Data volunteer:\n"
            f"- Nama: {volunteer.get('name')}\n"
            f"- Area tugas: {area}\n"
            f"- Tim: {', '.join(team) if team else 'belum ada data tim'}\n"
            f"- Kuota: {float(quota):g} kg"
        )

        if mission:
            remaining = self._remaining_days(mission.get("deadline"))
            remaining_text = (
                f"{remaining} hari lagi" if remaining is not None and remaining >= 0
                else "sudah lewat" if remaining is not None
                else "tidak diketahui"
            )
            mission_section = (
                f"Misi aktif:\n"
                f"- Judul: {mission.get('title')}\n"
                f"- Deskripsi: {mission.get('description') or '-'}\n"
                f"- Deadline: {mission.get('deadline')} ({remaining_text})\n"
                f"- Progress {volunteer.get('name')}: {progress_kg:g} kg "
                f"dari kuota {float(quota):g} kg"
            )
        else:
            mission_section = (
                "Misi aktif: belum ada misi yang diassign ke volunteer ini. "
                "Fasilitator akan menginformasikan misi berikutnya."
            )

        return f"{BASE_PROMPT}\n\n{volunteer_section}\n\n{mission_section}\n\n{SOP_SECTION}"

    @staticmethod
    def _remaining_days(deadline: str | None) -> int | None:
        if not deadline:
            return None
        try:
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            return (deadline_dt - datetime.now(timezone.utc)).days
        except ValueError:
            logger.warning("Unparseable mission deadline: %r", deadline)
            return None
