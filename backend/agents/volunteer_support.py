"""Volunteer support agent: emotional support, complaint handling, and plastic education."""

import logging
from datetime import datetime, timezone

from backend.database.supabase_client import db
from backend.utils.impact_calculator import ImpactCalculator
from . import progress_tracker
from .base_agent import BaseAgent, COMPLEX_MODEL

logger = logging.getLogger(__name__)

SITUATIONS = (
    "want_to_quit",
    "complaint",
    "motivation",
    "plastic_education",
    "general_qa",
)
DEFAULT_SITUATION = "general_qa"

SITUATION_PROMPT = """Klasifikasikan pesan volunteer ke TEPAT SATU situasi berikut. Balas HANYA dengan label situasinya, tanpa penjelasan.

Situasi:
- want_to_quit: mau berhenti, keluar, mundur, tidak sanggup, menyerah
- complaint: ada masalah, warga menolak, cuaca buruk, tidak ada plastik, konflik tim, alat rusak
- motivation: minta semangat, capek, lelah, bosan, butuh motivasi
- plastic_education: pertanyaan jenis plastik, daur ulang, dampak lingkungan, mikroplastik, alternatif plastik, cara edukasi warga
- general_qa: pertanyaan umum program, jadwal, prosedur

Contoh:
"saya mau berhenti jadi volunteer" → want_to_quit
"kayaknya saya nggak sanggup lanjut deh" → want_to_quit
"warga di sini nolak terus, gimana dong" → complaint
"hujan terus seminggu ini, susah ngumpulin" → complaint
"capek banget minggu ini" → motivation
"butuh semangat nih kak" → motivation
"plastik PET itu apa?" → plastic_education
"mikroplastik itu berbahaya ga?" → plastic_education
"gimana cara jelasin ke warga yang ga mau dengerin?" → plastic_education
"jadwal pengumpulan minggu depan gimana?" → general_qa"""

SITUATION_GUIDANCE = {
    "plastic_education": (
        "Jawab dengan fakta dari KNOWLEDGE BASE PLASTIK di atas. "
        "WAJIB sertakan minimal 1 angka atau statistik konkret. "
        "Kaitkan dengan konteks Indonesia/lokal bila memungkinkan. "
        "Jika volunteer bertanya cara menjelaskan ke orang lain: berikan skrip dan "
        "talking points yang bisa langsung dipakai. "
        "Akhiri dengan apa yang bisa volunteer LAKUKAN dengan info ini."
    ),
    "complaint": (
        "Empati dulu, baru bantu cari solusi. "
        "Jika warga tidak mau / menolak: berikan 3 tips persuasi yang spesifik. "
        "Jika soal cuaca/kondisi lapangan: akui kesulitannya, lalu sarankan "
        "workaround yang praktis."
    ),
    "want_to_quit": (
        "Empati secara mendalam dan ajukan pertanyaan terbuka tentang apa yang "
        "membuatnya berat. JANGAN langsung membujuk untuk bertahan. "
        "Fasilitator akan menghubungi secara personal untuk follow-up."
    ),
    "motivation": (
        "Sebutkan data progress spesifik volunteer ini (dari DATA VOLUNTEER di atas) "
        "dan kaitkan dengan dampak program (kg terkumpul, botol diselamatkan). "
        "Singkat dan menyemangati — bukan ceramah."
    ),
    "general_qa": (
        "Jawab pertanyaannya dengan jelas. Jika di luar topik plastik dan program, "
        "bantu secukupnya lalu arahkan kembali ke konteks program."
    ),
}

KNOWLEDGE_BASE = """=== KNOWLEDGE BASE PLASTIK ===

JENIS PLASTIK (berdasarkan kode segitiga di kemasan):
- PET / kode 1: botol bening (air minum, minuman ringan)
  → Paling mudah dan paling berharga untuk didaur ulang
  → Ciri: bening, ringan, bisa dipencet
- HDPE / kode 2: botol tebal (sampo, deterjen, jerigen)
  → Bisa didaur ulang, lebih kaku dari PET
  → Ciri: buram atau berwarna, lebih keras
- PVC / kode 3: pipa, kemasan blister
  → HINDARI — sulit didaur ulang, mengandung klorin berbahaya
  → Ciri: keras, tidak fleksibel
- LDPE / kode 4: kantong kresek, plastik wrap
  → Jarang diterima di fasilitas daur ulang biasa
  → Ciri: tipis, fleksibel, mudah sobek
- PP / kode 5: wadah makanan, sedotan, tutup botol
  → Bisa didaur ulang, tahan panas
  → Ciri: agak buram, tidak pecah saat dibengkokkan
- PS / kode 6: styrofoam, gelas plastik tipis
  → HINDARI — sulit didaur ulang, berbahaya bila dibakar
  → Ciri: ringan sekali, mudah hancur jadi serpihan
- Other / kode 7: campuran berbagai plastik
  → Umumnya tidak bisa didaur ulang
  → Termasuk botol galon, kacamata, laptop

FAKTA DAMPAK LINGKUNGAN (gunakan angka konkret ini):
- Plastik butuh 400–1000 tahun untuk terurai di alam
- 8 juta ton sampah plastik masuk laut setiap tahun di seluruh dunia
- Indonesia adalah penghasil sampah plastik laut TERBESAR KE-2 di dunia
  setelah Tiongkok (sumber: jurnal Science, 2015)
- 1 juta burung laut dan 100.000 mamalia laut mati tiap tahun akibat plastik
- Hanya 9% dari seluruh plastik yang pernah diproduksi berhasil didaur ulang
- Produksi plastik global: 400 juta ton per tahun dan terus naik

PANDUAN DAUR ULANG YANG BENAR:
- Pilah berdasarkan kode segitiga di bagian bawah kemasan
- Cuci/bilas plastik sebelum dikumpulkan — plastik kotor sering ditolak
- Gepengkan botol untuk menghemat ruang penyimpanan
- Plastik PET dan HDPE paling dicari dan paling bernilai
- Bank sampah adalah jalur utama distribusi di Indonesia
- Hindari mencampur jenis plastik yang berbeda dalam satu kantong

ALTERNATIF PENGGANTI PLASTIK SEKALI PAKAI:
- Kantong belanja: tas kain, anyaman, atau jaring
- Minuman: tumbler stainless atau botol kaca
- Sedotan: bambu, stainless, atau kertas
- Wadah makanan: beeswax wrap, bento box stainless
- Kantong sampah: plastik daur ulang atau paper bag
- Di Indonesia: tersedia kantong plastik berbasis singkong (biodegradable)
  yang terurai dalam 180 hari di kondisi alami

MIKROPLASTIK — fakta penting:
- Partikel plastik berukuran < 5mm yang terbentuk dari plastik yang terurai
- Ditemukan di: air minum kemasan, ikan dan seafood, garam dapur,
  bahkan dalam darah dan plasenta manusia
- Manusia rata-rata menelan 5 gram mikroplastik per minggu
  (setara 1 kartu kredit plastik — sumber: WWF, 2019)
- Berpotensi mengganggu sistem hormon dan reproduksi
- Hampir TIDAK MUNGKIN dihilangkan dari lingkungan setelah masuk

TIPS EDUKASI KE WARGA YANG SULIT DIYAKINKAN:
Skrip yang bisa langsung dipakai:

1. Untuk warga yang bilang "plastik sudah biasa, dari dulu juga ada":
   "Betul Bu/Pak, plastik memang sudah lama ada. Tapi tahukah plastik yang
   dibuang hari ini masih akan ada saat cucu kita sudah tua? Sampah plastik
   tidak hilang, hanya jadi makin kecil dan masuk ke tubuh ikan yang kita makan."

2. Untuk warga yang bilang "buang di sungai nanti hanyut sendiri":
   "Hanyutnya ke laut, Pak/Bu — laut kita sendiri. Dan ikan yang kita makan
   sudah mengandung serpihan plastik itu. Kita makan plastik sendiri."

3. Untuk warga yang apatis:
   "Tidak harus langsung sempurna. Cukup mulai dari 1 hal: pisahkan botol
   plastik sebelum dibuang. Itu sudah membantu sekali untuk program ini."

4. Untuk anak-anak (libatkan mereka untuk pengaruhi orang tua):
   "Kalau plastik ini dibuang sembarangan, ikan-ikan di laut akan memakannya
   dan bisa mati. Kamu mau bantu selamatkan ikan-ikan itu?\""""


class VolunteerSupportAgent(BaseAgent):
    """Supports volunteers emotionally and educates them about plastic."""

    def __init__(self) -> None:
        super().__init__(
            name="volunteer_support",
            description="Emotional support, complaint handling, and plastic education",
        )

    async def process(self, message: str, context: dict) -> str:
        telegram_id = context.get("telegram_id")
        volunteer = context.get("volunteer")
        if volunteer is None and telegram_id:
            volunteer = await self.get_volunteer(telegram_id)
        mission = context.get("mission")

        # 1. Conversation continuity
        history = await self.get_chat_history(telegram_id, limit=10) if telegram_id else []

        # 3. Situation classification (cheap Haiku call)
        situation = await self.detect_situation(message)

        # 2. Full system prompt + situation-specific instructions
        system_prompt = (
            self._build_system_prompt(volunteer, mission)
            + f"\n\n=== INSTRUKSI UNTUK SITUASI SAAT INI ({situation}) ===\n"
            + SITUATION_GUIDANCE[situation]
        )

        # 4. Sonnet for the actual response
        messages = history + [{"role": "user", "content": message}]
        response = await self.call_claude(system_prompt, messages, model=COMPLEX_MODEL)

        # 5. Escalation: quit intent always escalates; Claude can also flag a crisis
        name = volunteer["name"] if volunteer else f"Volunteer (telegram_id {telegram_id})"
        if situation == "want_to_quit":
            await progress_tracker._alert_fasilitator(
                f"⚠️ {name} is considering quitting: {message}"
            )
        elif "[ESCALATE]" in response:
            await progress_tracker._alert_fasilitator(
                f"⚠️ {name} butuh perhatian segera (krisis): {message}"
            )
        response = response.replace("[ESCALATE]", "").strip()

        # 6. Persist both sides
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", response, self.name)

        # 7. Return the cleaned response
        return response

    async def detect_situation(self, message: str) -> str:
        label = await self.call_claude(
            SITUATION_PROMPT, [{"role": "user", "content": message}], max_tokens=20
        )
        situation = label.strip().lower()
        if situation not in SITUATIONS:
            logger.warning("Invalid situation %r, defaulting to %s", situation, DEFAULT_SITUATION)
            return DEFAULT_SITUATION
        return situation

    def _build_system_prompt(self, volunteer: dict | None, mission: dict | None) -> str:
        if volunteer:
            team = volunteer.get("team") or []
            quota = float((mission or {}).get("quota_kg") or volunteer.get("quota_kg") or 0)
            reported_kg = self._reported_kg(volunteer["id"], (mission or {}).get("id"))
            pct = (reported_kg / quota * 100) if quota else 0
            impact = ImpactCalculator.format_impact_summary(reported_kg)
            deadline = (mission or {}).get("deadline")
            days_left = self._days_left(deadline)
            days_text = (
                f"{days_left} hari lagi" if days_left is not None and days_left >= 0
                else "sudah lewat" if days_left is not None
                else "belum ada misi aktif"
            )
            data_section = (
                f"=== DATA VOLUNTEER ===\n"
                f"Nama: {volunteer.get('name')}\n"
                f"Area: {volunteer.get('area')}\n"
                f"Tim: {', '.join(team) if team else 'belum ada data tim'}\n"
                f"Progress misi: {reported_kg:g}/{quota:g} kg ({pct:.0f}%)\n"
                f"Dampak sejauh ini: {impact['bottles']:,} botol diselamatkan, "
                f"{impact['co2_kg']:g} kg CO₂ dicegah\n"
                f"Minggu aktif: {self._weeks_active(volunteer.get('joined_at'))} minggu\n"
                f"Deadline: {deadline or '-'} ({days_text})\n"
                f"Status: {'aktif' if volunteer.get('is_active', True) else 'tidak aktif'}"
            )
        else:
            data_section = (
                "=== DATA VOLUNTEER ===\n"
                "Volunteer ini BELUM TERDAFTAR. Bantu pertanyaannya secukupnya dan "
                "sarankan registrasi: DM bot ini lalu ketik /start."
            )

        return f"""Kamu adalah Volunteer Support Agent untuk program "Generasi Bebas Plastik" di Indonesia.
Kamu memiliki DUA peran: (1) support emosional volunteer, (2) edukasi tentang plastik.

{data_section}

=== PERSONA ===
- Bahasa Indonesia santai dan hangat, pakai "kamu" bukan "Anda"
- Selalu sebut nama volunteer di awal respons
- Empati dulu, solusi kemudian
- Maksimal 4-5 kalimat kecuali diminta penjelasan panjang
- Gunakan emoji secukupnya untuk kehangatan

{KNOWLEDGE_BASE}

=== BATASAN ===
- Jika ditanya di luar topik plastik dan program: bantu secukupnya,
  lalu arahkan kembali ke konteks program
- Jangan memberi saran medis atau hukum yang spesifik
- Untuk situasi krisis (volunteer sangat tertekan): tambahkan [ESCALATE]"""

    @staticmethod
    def _reported_kg(volunteer_id: str, mission_id: str | None) -> float:
        query = db.table("reports").select("kg_collected").eq("volunteer_id", volunteer_id)
        if mission_id:
            query = query.eq("mission_id", mission_id)
        rows = query.execute().data or []
        return sum(float(r["kg_collected"]) for r in rows)

    @staticmethod
    def _weeks_active(joined_at: str | None) -> int:
        if not joined_at:
            return 0
        try:
            joined = datetime.fromisoformat(joined_at.replace("Z", "+00:00"))
        except ValueError:
            return 0
        return max((datetime.now(timezone.utc) - joined).days // 7, 0)

    @staticmethod
    def _days_left(deadline: str | None) -> int | None:
        if not deadline:
            return None
        try:
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Unparseable mission deadline: %r", deadline)
            return None
        return (deadline_dt - datetime.now(timezone.utc)).days
