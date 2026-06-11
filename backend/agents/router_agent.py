"""Router agent: classifies every incoming message and delegates to a specialist agent."""

import logging

from backend.config import settings
from .base_agent import BaseAgent
from .content_creator import ContentCreatorAgent
from .fasilitator_hub import FasilitatorHubAgent
from .impact_analyzer import ImpactAnalyzerAgent
from .mission_briefing import MissionBriefingAgent
from .progress_tracker import ProgressTrackerAgent, has_pending_report
from .volunteer_support import VolunteerSupportAgent

logger = logging.getLogger(__name__)

DEFAULT_INTENT = "volunteer_support"

# fasilitator_hub is intentionally absent: it is reachable only via the
# telegram_id check in process(), never via classification.
VALID_INTENTS = (
    "mission_briefing",
    "progress_tracker",
    "volunteer_support",
    "plastic_education",  # handled by the volunteer_support agent
    "content_creator",
    "impact_analyzer",
)

CLASSIFICATION_PROMPT = """Kamu adalah router untuk Macca, platform koordinasi volunteer pengumpulan sampah plastik di Jakarta. Klasifikasikan pesan volunteer ke dalam TEPAT SATU kategori berikut. Balas HANYA dengan string kategorinya, tanpa tanda baca atau penjelasan apa pun.

Kategori:
- mission_briefing: pertanyaan tentang tugas, area, kuota, deadline, SOP laporan, apa yang harus dilakukan
- progress_tracker: laporan plastik terkumpul (mengandung angka + kg/kilo + lokasi), pertanyaan tentang progress atau sisa target pribadi
- volunteer_support: masalah, keluhan, mau berhenti, butuh motivasi, pertanyaan umum, kebingungan
- plastic_education: pertanyaan tentang jenis plastik, kode plastik, daur ulang, dampak plastik ke lingkungan, mikroplastik, alternatif plastik, cara edukasi/menjelaskan ke warga
- content_creator: minta dibuatkan konten media sosial, caption, post, teks pengumuman
- impact_analyzer: pertanyaan tentang dampak total program, statistik keseluruhan, laporan untuk sponsor/donor

Contoh:
"apa tugas saya minggu ini?" → mission_briefing
"deadline misi kapan ya?" → mission_briefing
"area saya di mana?" → mission_briefing
"kuota saya berapa kg?" → mission_briefing
"apa yang harus saya lakukan hari ini?" → mission_briefing
"sop laporan gimana?" → mission_briefing
"laporan 18 kg menteng" → progress_tracker
"udah nih 25 kilo di cikini [foto]" → progress_tracker
"saya sudah kumpul 5 kg di senen" → progress_tracker
"laporan foto" → progress_tracker
"progress saya udah berapa kg?" → progress_tracker
"kurang berapa lagi biar capai target?" → progress_tracker
"capek banget pengen nyerah" → volunteer_support
"kenapa saya harus ikut program ini?" → volunteer_support
"saya mau berhenti jadi volunteer" → volunteer_support
"timbangan saya rusak, gimana dong?" → volunteer_support
"halo, bot ini bisa apa aja?" → volunteer_support
"minggu depan saya tidak bisa ikut, izin ya" → volunteer_support
"plastik PET itu apa?" → plastic_education
"bedanya plastik kode 1 sama kode 2 gimana?" → plastic_education
"kenapa plastik bahaya untuk lingkungan?" → plastic_education
"mikroplastik itu berbahaya ga?" → plastic_education
"gimana cara daur ulang yang bener?" → plastic_education
"alternatif plastik sekali pakai apa aja?" → plastic_education
"gimana cara jelasin ke warga yang ga mau dengerin?" → plastic_education
"styrofoam bisa didaur ulang ga?" → plastic_education
"kresek kode berapa?" → plastic_education
"indonesia buang plastik berapa banyak?" → plastic_education
"buatkan caption instagram hari ini" → content_creator
"tolong bikin post story wa tentang misi minggu ini" → content_creator
"bikin teks pengumuman buat grup dong" → content_creator
"total program berapa kg sejauh ini?" → impact_analyzer
"sudah berapa total yang terkumpul?" → impact_analyzer
"berapa volunteer aktif sekarang?" → impact_analyzer
"buat ringkasan dampak program buat sponsor" → impact_analyzer
"rekap statistik mingguan buat laporan donor" → impact_analyzer"""


class RouterAgent(BaseAgent):
    """Classifies intent with a cheap Haiku call, then delegates to the matching agent."""

    def __init__(self, agents: dict[str, BaseAgent] | None = None) -> None:
        super().__init__(
            name="router",
            description="Classifies message intent and dispatches to specialist agents",
        )
        if agents is None:
            volunteer_support = VolunteerSupportAgent()
            agents = {
                "mission_briefing": MissionBriefingAgent(),
                "progress_tracker": ProgressTrackerAgent(),
                "volunteer_support": volunteer_support,
                # education questions are handled by the same support agent
                "plastic_education": volunteer_support,
                "content_creator": ContentCreatorAgent(),
                "impact_analyzer": ImpactAnalyzerAgent(),
                "fasilitator_hub": FasilitatorHubAgent(),
            }
        self._agents = agents
        self.last_agent: str = self.name

    async def process(self, message: str, context: dict) -> str:
        """Classify the message and return the intent category string."""
        # 1. Fasilitator always goes to the fasilitator hub
        if context.get("telegram_id") == settings.fasilitator_telegram_id:
            return "fasilitator_hub"

        # 1b. A volunteer mid-report (pending kg/location/confirmation) skips
        #     classification — their reply belongs to the progress tracker
        if has_pending_report(context.get("telegram_id")):
            return "progress_tracker"

        # 2-3. Classify with Claude Haiku and normalise the label
        label = await self.call_claude(
            CLASSIFICATION_PROMPT,
            [{"role": "user", "content": message}],
            max_tokens=20,
        )
        intent = label.strip().lower()

        # 4. Unknown labels (including fasilitator_hub for non-fasilitators)
        #    fall back to volunteer_support
        if intent not in VALID_INTENTS:
            logger.warning("Invalid intent %r, defaulting to %s", intent, DEFAULT_INTENT)
            intent = DEFAULT_INTENT

        # 5. Return the category string
        return intent

    async def route(self, message: str, context: dict) -> str:
        """Classify, delegate to the matching agent, and return its response."""
        intent = await self.process(message, context)
        agent = self._agents[intent]
        self.last_agent = agent.name
        logger.info("Routing message to %s", agent.name)
        return await agent.process(message, context)
