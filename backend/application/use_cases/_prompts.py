"""Prompts owned by the application layer (use cases).

Kept separate from ``backend.agents.prompts`` so use cases don't have to
import presentation-layer strings; agents that still need these strings
can re-export from here.
"""

BASE_BRIEFING_PROMPT = (
    "Kamu adalah asisten briefing misi untuk Macca, platform koordinasi volunteer "
    "pengumpulan sampah plastik (Generasi Bebas Plastik). "
    "Tugasmu menjawab pertanyaan volunteer tentang tugas, misi, area, kuota, deadline, "
    "dan SOP berdasarkan data di bawah. "
    "Jawab dalam Bahasa Indonesia yang ramah, singkat, jelas, dan memotivasi. "
    "Jika data tidak tersedia, katakan dengan jujur dan sarankan menghubungi fasilitator. "
    "Format jawaban untuk Telegram (boleh pakai <b>bold</b> dan emoji secukupnya)."
)

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

# User-facing reply strings used when domain rules short-circuit the LLM.
QUOTA_REACHED_MSG = (
    "Kamu sudah 2x tanya tentang misi hari ini 😊 "
    "Untuk info lengkap silakan buka panduan program ya!"
)

LAST_FREE_NOTICE = (
    "\n\nIni adalah info misi terakhir yang bisa aku berikan hari ini. "
    "Kalau masih ada pertanyaan, cek panduan program ya! 📖"
)

NOT_REGISTERED_MSG = (
    "Kamu belum terdaftar sebagai volunteer. "
    "Silakan DM bot ini dan ketik /start untuk registrasi ya!"
)

NO_ACTIVE_MISSION_HINT = (
    "Misi aktif: belum ada misi yang diassign ke volunteer ini. "
    "Fasilitator akan menginformasikan misi berikutnya."
)
