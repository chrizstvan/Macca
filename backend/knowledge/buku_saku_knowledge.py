"""
Knowledge base: Buku Saku Relawan Generasi Bebas Plastik Batch 9.

Cara pakai:
    from backend.knowledge.buku_saku_knowledge import BUKU_SAKU_GBP

    system_prompt = f'''{persona_instructions}

    {BUKU_SAKU_GBP}

    Gunakan informasi di atas untuk menjawab pertanyaan volunteer tentang
    program. Kalau jawaban tidak ada di buku saku, katakan jujur dan arahkan
    volunteer untuk bertanya ke fasilitator.'''

Tidak perlu RAG / vector DB — dokumen ini kecil (~6.000 token), cukup
di-inject langsung ke system prompt. Edit langsung file ini kalau ada
perubahan info program.
"""

BUKU_SAKU_GBP = """
=========================================================================
BUKU SAKU RELAWAN — GENERASI BEBAS PLASTIK BATCH 9
(Program dari Indorelawan, didukung ParagonCorp, Novo Club, Indorelawan.org)
=========================================================================

## A. TENTANG PROGRAM
Generasi Relawan adalah inisiatif Indorelawan untuk mendorong anak muda
berperan aktif mengatasi isu sosial di Indonesia.

Generasi Bebas Plastik (GBP) adalah salah satu pilar Generasi Relawan,
fokus pada kebiasaan minim plastik dan solusi nyata atas masalah sampah
plastik. Selama 1 bulan, relawan mengikuti:
- 2 kelas pembekalan interaktif
- 2 tantangan aksi (tantangan individu & proyek sosial)

Tujuan: membentuk generasi muda sebagai agen perubahan yang peduli dan
punya inisiatif sosial untuk mengatasi masalah sampah plastik di lingkungan
tempat tinggalnya.

## B. TIMELINE PROGRAM (Juni–Agustus 2026)
- Kamis, 16 Juli 2026 — Onboarding Generasi Relawan
- Sabtu, 18 Juli 2026 (10.00–12.00 WIB) — Kelas #1: "Krisis Sampah di
  Indonesia: Plastik Hari Ini, Dampak Esok Hari"
- 18–24 Juli 2026 — Periode Tantangan Individu: "Less Plastic, More Life"
- 24 Juli 2026 — Batas pengisian form laporan tantangan individu
- Sabtu, 25 Juli 2026 (10.00–12.00 WIB) — Kelas #2: "Hidup Minim Plastik:
  Kebiasaan Kecil untuk Perubahan Besar"
- 29 Juli–12 Agustus 2026 — Periode Proyek Sosial: "Eco Bank Challenge"
- Rabu, 12 Agustus 2026 — Batas pengisian form laporan proyek sosial
- Sabtu, 15 Agustus 2026 — Inagurasi

## C. KELAS

### Kelas #1 — Sabtu, 18 Juli 2026, 10.00–12.00 WIB
Pemateri: Sarah Rauzana (Program Manager Dietplastik Indonesia)
Topik: "Krisis Sampah di Indonesia: Plastik Hari Ini, Dampak Esok Hari"
Yang dipelajari:
- Kondisi & urgensi masalah sampah plastik di Indonesia
- Fakta dan data terkini terkait sampah plastik
- Dampak plastik terhadap lingkungan dan kesehatan
- Peran individu menjadi bagian dari solusi lewat perubahan perilaku

### Kelas #2 — Sabtu, 25 Juli 2026, 10.00–12.00 WIB
Pemateri: Nada Arini (Penggiat Lingkungan)
Topik: "Hidup Minim Plastik: Kebiasaan Kecil untuk Perubahan Besar"
Yang dipelajari:
- Langkah praktis mengurangi plastik sekali pakai
- Prinsip 5R: Refuse, Reduce, Reuse, Recycle, Rot
- Cara berkontribusi dalam pengelolaan sampah (aksi individu & komunitas)

### Panduan Kelas
1. Bergabung via laptop/HP/device memadai (untuk buka Google Slides, Slido,
   Google Form saat kelas)
2. Menyiapkan catatan
3. Siapkan camilan & minuman favorit

### Kesepakatan Kelas
- Bergabung di Zoom sejak 15 menit sebelum kelas mulai. Presensi lewat link
  untuk menghitung poin kehadiran. Link Zoom diberikan H-1 oleh fasilitator.
- Format nama Zoom: "nomor kelompok - nama kelompok - nama panggilan"
  (contoh: 7 - BPJS - Bunga)
- Aktif bertanya & berdiskusi (bisa lewat kolom chat)
- Aktifkan kamera & pakai Virtual Background (unduh: bit.ly/vbgGBP9)
- Komunikasi dengan fasilitator jika ada kendala
- Buat konten "Belajar Apa Hari Ini?" (BAHI) di Instastory setelah kelas

## D. TANTANGAN

### 1. TANTANGAN INDIVIDU — "Less Plastic, More Life" (18–24 Juli 2026)
Wajib dikerjakan tiap relawan secara individu. 3 aktivitas utama, masing-masing
cukup 1 kali. Waktu fleksibel, tapi KETIGA aktivitas WAJIB selesai (kalau tidak,
tidak dapat sertifikat & tidak bisa lanjut ke Proyek Sosial):

a. Reduce/Refuse — kurangi/menolak plastik sekali pakai. Pilih salah satu:
   - Opsi A: Bawa botol minum (tumbler) pribadi
   - Opsi B: Bawa kantong belanja (tote bag) sendiri
   - Opsi C: Bawa wadah/alat makan sendiri
   Dokumentasikan (foto/video) & unggah ke medsos dengan caption.

b. Reuse/Repair — perpanjang umur barang (terutama plastik):
   - Manfaatkan kembali wadah plastik, ATAU perbaiki barang rusak
   - Dokumentasikan proses (foto/video) & unggah ke medsos.

c. Recycle — olah sampah plastik jadi barang baru. Pilih salah satu:
   - Opsi A: Tempat pensil dari botol bekas
   - Opsi B: Anyaman dari sampah kemasan sachet
   - Opsi C: Pot tanaman dari botol/sachet
   Wajib didokumentasikan (foto/video) & unggah dengan caption ajakan.

Ketentuan Unggahan Medsos (WAJIB):
- Hashtag: #GenerasiBebasPlastik #GBPBatch9 #GBPLessPlasticMoreLife
- Tag: @indorelawan dan @generasibebasplastik
- Khusus IG Story: masukkan ke Highlights bernama "GBP9"
- Deadline: unggah konten + isi Google Form maks 24 Juli 2026, 23:59 WIB

Bobot poin bentuk unggahan:
- Instagram Story: 5 poin
- Instagram Feeds: 10 poin
- Instagram Reels: 15 poin

### 2. PROYEK SOSIAL — "Eco Bank Challenge" (29 Juli–12 Agustus 2026)
Syarat: sudah hadir 2 kelas wajib + selesai tantangan individu.
Boleh kelompok atau individu.

TAHAP 1 — Survei Data Bank Sampah (29 Juli–4 Agustus 2026):
- Survei bank sampah sebanyak-banyaknya di area tempat tinggal
- Cek spreadsheet panitia dulu agar tidak duplikat
- Isi Google Form Pelaporan Bank Sampah dengan data: Nama Bank Sampah & jenis
  lembaga, penanggung jawab & no telp, jumlah pengurus & jadwal operasional,
  kegiatan/program, alamat lengkap & titik Google Maps
- Deadline Tahap 1: submit sebelum 4 Agustus 2026, 23:59 WIB

TAHAP 2 — Kunjungan & Pembuatan Konten (setelah Tahap 1–12 Agustus 2026):
Pilihan A (Kelompok):
- Tentukan Ketua & Wakil Ketua
- Pilih 1–2 bank sampah (maks 3) untuk dikunjungi
- Tiap relawan bawa sampah terpilah dari rumah untuk disetor
- Rekam proses penyetoran (tunjukkan nama bank sampah & jumlah sampah)
- Perwakilan unggah video ke medsos
Pilihan B (Individu):
- Pilih 1 bank sampah dari survei mandiri
- Setor sampah terpilah dari rumah
- Rekam proses (tunjukkan nama bank sampah & jumlah sampah)
- Unggah ke Instagram (WAJIB Reels)

Aturan Video (Khusus Kelompok):
- Durasi 60–90 detik
- Nama bank sampah & jumlah sampah terlihat jelas
- Wajib kombinasi min. 2 tema: Kolaborasi Bank Sampah, Vlog/Storytelling
  "Come with me to the Ecobank!", EcoBank Campaign

Publikasi & Pelaporan:
- IG Reels: diunggah 1 akun perwakilan (tim) atau akun pribadi (individu)
- IG Story (kelompok): di-share ulang min. 3 anggota + masuk Highlights
- Hashtag: #GenerasiBebasPlastik #GBPBatch9 #GroupProject #GBPEcoBankChallenge
- Tag: @indorelawan, @generasibebasplastik, & akun IG fasilitator kelompok
- Pelaporan akhir: Ketua isi Google Form kelompok / individu isi form individu
- Deadline: 12 Agustus 2026, 12:00 WIB

Sistem Penilaian Proyek Sosial:
- Tema (40 poin): gambarkan kegiatan bank sampah detail (survei, setor, wawancara)
- Kreativitas (30 poin): kualitas editing, alur cerita, nilai tambah jika >2 tema
- Pesan (20 poin): edukasi/ajakan mudah dipahami, singkat, jelas, impactful
- Bobot Sampah (10 poin): jumlah sampah yang disetorkan

## E. PENILAIAN, SERTIFIKAT & APRESIASI

### Penilaian Relawan (poin):
Unggahan:
- Mengunggah Twibbon: 10 poin
Peran & Keaktifan:
- Ketua Kelompok: 10 poin
- Wakil Ketua Kelompok: 10 poin
- Bertanya lewat Slido saat kelas: 10 poin/kelas
- Bertanya lewat raise hand: 20 poin/kelas
- Mengerjakan BAHI: 10 poin/kelas (BAHI terbaik +10 poin)
Kehadiran:
- Presensi Onboarding: 10 poin
- Presensi Kelas 1: 20 poin
- Presensi Kelas 2: 20 poin
- Presensi Inagurasi: 10 poin
Pengisian Tautan:
- Pre-Test Program: 10 poin
- Pre-Test Kelas: 10 poin/kelas
- Post-Test Kelas: 10 poin/kelas
- Post-Test Program: 10 poin
Tantangan (sesuai ketentuan):
- Tantangan Individu "Less Plastic More Life"
- Survey Bank Sampah
- Proyek Sosial "Eco Bank Challenge"

### Syarat Sertifikat:
Menyelesaikan seluruh rangkaian program:
- Hadir 2 kelas online (Kelas 1 & 2), dibuktikan lewat presensi
- Mengisi pre-test dan post-test
- Menyelesaikan tantangan individu (syarat wajib untuk ikut Proyek Sosial)

### Apresiasi:
- Relawan Terbaik: paling menginspirasi & aktif, dinilai dari akumulasi poin
  kelas, tantangan, dan keaktifan
- Sertifikat Program: bagi yang menyelesaikan program & memenuhi syarat

## F. TIMELINE PENGISIAN TAUTAN (deadline tiap form)
1. Pretest Program — Jumat, 17 Juli 2026, 11:00 WIB
2. Presensi — 1 jam setelah sesi
3. Pretest Kelas 1 — 18 Juli 2026, 10:15 WIB
4. Posttest Kelas 1 + Laporan BAHI — 18 Juli 2026, 14:00 WIB
5. Pretest Kelas 2 — 25 Juli 2026, 10:15 WIB
6. Posttest Kelas 2 + Laporan BAHI — 25 Juli 2026, 14:00 WIB
7. Form Pelaporan Tantangan Individu — 24 Juli 2026, 23:59 WIB
8. Form Pelaporan Survei Bank Sampah — 4 Agustus 2026, 23:59 WIB
9. Form Pelaporan Proyek Sosial — 12 Agustus 2026, 12:00 WIB
10. Posttest Program — Minggu, 9 Agustus 2026, 12:00 WIB

## G. LINK PENTING
1. Pembagian Kelompok + ID Relawan: s.id/RelawanGenerasiBebasPlastik9
2. Folder Relawan: bit.ly/FolderRelawan9
3. Virtual Background: bit.ly/vbgGBP9
4. Pretest Posttest Program: bit.ly/programtestGBP9
5. Presensi: bit.ly/absensiGBP9
6. Pretest Posttest Kelas 1: bit.ly/testkelas1GBP9
7. Pretest Posttest Kelas 2: bit.ly/testkelas2GBP9
8. Template BAHI: bit.ly/TemplateBAHI9
9. Pelaporan Tantangan Individu: bit.ly/PelaporanTantanganIndividu
10. Pelaporan Survey Bank Sampah: bit.ly/pelaporanSBS
11. Pelaporan Proyek Sosial: bit.ly/PelaporanProyekSosial
12. Grup WhatsApp Komunitas GBP (untuk ngobrol dengan sesama volunteer &
    fasilitator, sharing progress, info terbaru):
    https://chat.whatsapp.com/LXHEKUyqyEfL1fDJOKQclA

## H. REKOMENDASI MATERI BELAJAR
- Video BBC: "Kantong plastik: Awalnya diciptakan untuk selamatkan Bumi"
- Video Kok Bisa: "Seberapa Banyak Sampah Plastik di Dunia?" & "Kenapa Kamu
  Jadi Masalah?"
- Instagram: Zero Waste Nusantara (@zerowastenusantara)
- Film Dokumenter: Pulau Plastik (2020), Semesta (2020), Tenggelam Dalam Diam
  (2021), Seaspiracy (2021)
- Film KLHK: Bude Jo Belajar Kelola Sampah
- Website: Data Bank Sampah (Zero Waste Indonesia)
"""
