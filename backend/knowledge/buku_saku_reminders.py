"""
Structured buku saku data untuk generate reminder (Fasilitator Hub).

Ini versi machine-readable dari buku saku — dipakai Fasilitator Hub sebagai
FALLBACK saat dashboard (action_items) tidak punya data yang diminta.

Prioritas resolusi (lihat A.2b di add-on guide):
  1. Dashboard (action_items) menang
  2. Buku saku (file ini) fallback
  3. Tanya balik ke fasilitator

Beda dengan buku_saku_knowledge.py:
  - buku_saku_knowledge.py  = full-text, untuk Volunteer Support jawab pertanyaan
  - buku_saku_reminders.py  = structured dict, untuk Fasilitator Hub buat reminder

Kalau ada perubahan jadwal/link, edit di dashboard (bukan file ini) supaya
override otomatis. File ini hanya baseline default program.
"""

BUKU_SAKU_ITEMS = {
    # ---- Pre-test / Post-test ----
    "pretest_program": {
        "type": "pre_test",
        "title": "Pretest Program",
        "deadline": "2026-07-17 11:00",
        "link_url": "bit.ly/programtestGBP9",
    },
    "pretest_kelas_1": {
        "type": "pre_test",
        "title": "Pretest Kelas 1",
        "deadline": "2026-07-18 10:15",
        "link_url": "bit.ly/testkelas1GBP9",
    },
    "posttest_kelas_1": {
        "type": "post_test",
        "title": "Posttest Kelas 1 + Laporan BAHI",
        "deadline": "2026-07-18 14:00",
        "link_url": "bit.ly/testkelas1GBP9",
    },
    "pretest_kelas_2": {
        "type": "pre_test",
        "title": "Pretest Kelas 2",
        "deadline": "2026-07-25 10:15",
        "link_url": "bit.ly/testkelas2GBP9",
    },
    "posttest_kelas_2": {
        "type": "post_test",
        "title": "Posttest Kelas 2 + Laporan BAHI",
        "deadline": "2026-07-25 14:00",
        "link_url": "bit.ly/testkelas2GBP9",
    },
    "posttest_program": {
        "type": "post_test",
        "title": "Posttest Program",
        "deadline": "2026-08-09 12:00",
        "link_url": "bit.ly/programtestGBP9",
    },

    # ---- Kelas ----
    "kelas_1": {
        "type": "kelas",
        "title": "Kelas #1 Krisis Sampah di Indonesia",
        "scheduled_at": "2026-07-18 10:00",
        "location": "Zoom (link diberikan H-1 oleh fasilitator)",
        "description": "Pemateri: Sarah Rauzana (Program Manager Dietplastik Indonesia). "
                       "Format nama Zoom: nomor kelompok - nama kelompok - nama panggilan.",
    },
    "kelas_2": {
        "type": "kelas",
        "title": "Kelas #2 Hidup Minim Plastik",
        "scheduled_at": "2026-07-25 10:00",
        "location": "Zoom (link diberikan H-1 oleh fasilitator)",
        "description": "Pemateri: Nada Arini (Penggiat Lingkungan). Materi: prinsip 5R.",
    },

    # ---- Presensi ----
    "presensi": {
        "type": "presensi",
        "title": "Presensi Kelas",
        "link_url": "bit.ly/absensiGBP9",
        "description": "Diisi maksimal 1 jam setelah sesi berakhir.",
    },

    # ---- Submission / Laporan ----
    "tantangan_individu": {
        "type": "submission",
        "title": "Laporan Tantangan Individu (Less Plastic More Life)",
        "deadline": "2026-07-24 23:59",
        "link_url": "bit.ly/PelaporanTantanganIndividu",
        "description": "3 aktivitas: Reduce/Refuse, Reuse/Repair, Recycle. "
                       "Wajib dokumentasi IG + hashtag + tag akun resmi.",
    },
    "survei_bank_sampah": {
        "type": "submission",
        "title": "Laporan Survei Bank Sampah",
        "deadline": "2026-08-04 23:59",
        "link_url": "bit.ly/pelaporanSBS",
        "description": "Cek spreadsheet panitia dulu agar tidak duplikat data.",
    },
    "proyek_sosial": {
        "type": "submission",
        "title": "Laporan Proyek Sosial (Eco Bank Challenge)",
        "deadline": "2026-08-12 12:00",
        "link_url": "bit.ly/PelaporanProyekSosial",
        "description": "Kunjungi bank sampah, setor sampah terpilah, buat konten IG Reels.",
    },

    # ---- Tautan / Buku saku ----
    "twibbon": {
        "type": "tautan",
        "title": "Unggah Twibbon",
        "description": "Unggah twibbon program (10 poin).",
    },
    "buku_saku": {
        "type": "buku_saku",
        "title": "Buku Saku Relawan",
        "description": "Panduan lengkap program GBP Batch 9.",
    },
}


def match_buku_saku_item(text: str, type_hint: str = None) -> dict | None:
    """
    Cari item buku saku dari penyebutan fasilitator.
    Returns: single dict | {"multiple": [...]} | None

    Matching pakai skor: hitung berapa banyak kata dari input yang cocok dengan
    title/key tiap item. Item dengan skor tertinggi menang. Kalau ada beberapa
    item dengan skor tertinggi yang sama -> minta klarifikasi (multiple).

    NOTE: Ini fallback sederhana. Untuk matching yang lebih pintar (semantic),
    Fasilitator Hub bisa pakai Claude Haiku seperti di find_by_mention()
    lapis 3 (lihat A.2 add-on guide). File ini cukup untuk exact/keyword match.
    """
    text_low = text.lower().strip()
    # Keep words len>1 AND single digits (so "1"/"2" in "kelas 1" survives)
    input_words = [w for w in text_low.replace("-", " ").split()
                   if len(w) > 1 or w.isdigit()]
    if not input_words:
        return None

    scored = []
    for key, item in BUKU_SAKU_ITEMS.items():
        if type_hint is not None and item.get("type") != type_hint:
            continue

        haystack = (item["title"] + " " + key.replace("_", " ")).lower()

        # Score = jumlah kata input yang muncul di title/key item
        score = sum(1 for w in input_words if w in haystack)

        # Bonus besar kalau angka spesifik cocok (kelas 1 vs kelas 2, dst)
        # Ini bikin "pretest kelas 1" prefer "Pretest Kelas 1" bukan "Kelas 2"
        for w in input_words:
            if w.isdigit() and w in haystack:
                score += 3

        # Bonus kalau SEMUA kata input cocok (match kuat)
        if score >= len(input_words) and all(w in haystack for w in input_words):
            score += 2

        if score > 0:
            found = dict(item)
            found["_source"] = "buku_saku"
            found["_key"] = key
            scored.append((score, found))

    if not scored:
        return None

    # Ambil skor tertinggi
    max_score = max(s for s, _ in scored)
    top = [item for s, item in scored if s == max_score]

    if len(top) == 1:
        return top[0]
    return {"multiple": top}
