"""Fasilitator hub agent providing operational tools for mission facilitators."""

import logging
import re
from collections import defaultdict

from datetime import datetime, timedelta, timezone

from backend.utils.date_utils import days_since as _shared_days_since
from backend.utils.query_utils import find_target_volunteer

from .base_agent import BaseAgent, COMPLEX_MODEL
from .prompts.fasilitator_hub import (
    DRAFT_GUIDANCE,
    PSYCH_GUIDANCE,
    STRATEGY_GUIDANCE,
    SYSTEM_PROMPT,
)
from backend.database.supabase_client import db
from backend.utils.ranking_calculator import RankingCalculator

logger = logging.getLogger(__name__)

LEADERBOARD_KEYWORDS = ("ranking", "leaderboard", "peringkat", "rank")

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


class FasilitatorHubAgent(BaseAgent):
    """Operational summaries, flagged-report digests, broadcast drafting, and strategic consultation for fasilitators."""

    def __init__(self) -> None:
        super().__init__(
            name="fasilitator_hub",
            description="Operational tools and summaries for fasilitators",
        )

    async def process(self, message: str, context: dict) -> str:
        """Handle a fasilitator request; non-fasilitators are redirected politely."""
        context = self.build_context_flags(context)
        volunteer = await self.get_volunteer_flexible(context)
        if volunteer is not None:
            context.setdefault("volunteer", volunteer)
        telegram_id = context.get("telegram_id")

        if not context["is_fasilitator"]:
            # Limited peer-query path — permitted by ALLOW_PEER_QUERY.
            if context.get("_limited_peer_query"):
                reply = await self.handle_volunteer_query(message, context)
                reply = self._append_suggestions(reply, "get_volunteer_detail")
                await self.save_chat_history(telegram_id, "user", message, self.name)
                await self.save_chat_history(telegram_id, "assistant", reply, self.name)
                return reply
            return (
                "This command is only available to the fasilitator. "
                "If you need help, just ask me a question directly!"
            )

        # Q&A relay — fasilitator forwards a volunteer question and (optionally)
        # asks the bot to DM the volunteer directly.
        stripped = message.strip()
        qa_match = QA_PATTERN.match(stripped)
        if qa_match:
            target_phone = qa_match.group(1)
            question = (qa_match.group(2) or "").strip()
            reply = await self._handle_qa(question, target_phone)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        send_match = SEND_PATTERN.match(stripped)
        if send_match:
            target_phone = send_match.group(1) or ""
            text_to_send = (send_match.group(2) or "").strip()
            reply = await self._handle_send(target_phone, text_to_send)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # /remind slash — bulk volunteer notifications.
        remind_match = REMIND_PATTERN.match(stripped)
        if remind_match:
            reply = await self._handle_remind_slash(
                subtype=(remind_match.group(1) or "").lower() or None,
                arg=(remind_match.group(2) or "").strip(),
            )
            reply = self._append_suggestions(reply, "send_reminder")
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        # Capture project-context updates before anything else — single-turn
        # acknowledgement, no Claude call needed.
        captured = self._capture_project_context(message)
        if captured is not None:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", captured, self.name)
            return captured

        # Phase 6 intent classification — dispatch dedicated handlers BEFORE the
        # legacy strategy/psych/draft fallback.
        try:
            intent = await self._classify_command(message)
        except Exception as exc:
            logger.warning("intent classify failed: %s", exc)
            intent = "default"

        if intent != "default":
            try:
                reply = await self._dispatch_intent(intent, message, context)
            except Exception as exc:
                logger.exception("intent handler %s crashed: %s", intent, exc)
                reply = "Maaf, ada error saat menjalankan perintah itu. Coba ulangi atau ketik permintaan lain."
            reply = self._append_suggestions(reply, intent)
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        lowered = message.lower()
        is_strategy = any(kw in lowered for kw in STRATEGY_KEYWORDS)
        is_psych = any(kw in lowered for kw in PSYCH_KEYWORDS)
        draft_match = DRAFT_PATTERN.search(message)

        volunteers = (
            db.table("volunteers").select("id, name, area, quota_kg, is_active, telegram_id, phone").execute().data
            or []
        )

        # Draft path takes priority — fasilitator already accepted the offer
        # to draft a personalised message.
        if draft_match:
            target = self._find_target_by_name(message, volunteers)
            reply = await self._handle_draft_message(target)
            reply = self._append_suggestions(reply, "default")
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply

        if is_psych:
            target = self._find_target_by_name(message, volunteers)
            reply = await self._handle_psych_guidance(message, target, telegram_id)
            reply = self._append_suggestions(reply, "default")
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
            return reply
        flagged = (
            db.table("reports")
            .select("kg_collected, location, flag_reason, reported_at")
            .eq("is_flagged", True)
            .eq("verified", False)
            .execute()
            .data
            or []
        )
        extra = (
            f"\n\nVolunteers ({len(volunteers)}): {volunteers}"
            f"\nUnverified flagged reports ({len(flagged)}): {flagged}"
        )

        if any(kw in message.lower() for kw in LEADERBOARD_KEYWORDS):
            leaderboard = await RankingCalculator().get_leaderboard(limit=10)
            if leaderboard:
                extra += f"\n\nLeaderboard (top {len(leaderboard)}): {leaderboard}"
            else:
                extra += "\n\nLeaderboard: belum tersedia (jalankan update ranking)."

        if is_strategy:
            strategy_block = await self._build_strategy_block(volunteers, telegram_id)
            extra += strategy_block

        system_prompt = SYSTEM_PROMPT + (STRATEGY_GUIDANCE if is_strategy else "")
        # Sonnet for strategy consultations (quality matters); Haiku otherwise.
        model = COMPLEX_MODEL if is_strategy else "claude-haiku-4-5-20251001"

        history = await self.get_chat_history(telegram_id)
        messages = history + [{"role": "user", "content": message}]

        reply = await self.call_claude(system_prompt + extra, messages, model=model, max_tokens=2000)
        reply = self._append_suggestions(reply, "default")
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply

    # ------------------------------------------------------------------ #
    # Q&A relay                                                           #
    # ------------------------------------------------------------------ #

    async def _handle_qa(
        self, question: str, target_phone: str | None
    ) -> str:
        """Generate a copy-and-forward answer for a volunteer question."""
        if not question:
            return (
                "Format: `/qa [pertanyaan]` atau `/qa 628xxxxxxxxx: [pertanyaan]`"
            )
        answer = await self.call_claude(
            QA_SYSTEM_PROMPT,
            [{"role": "user", "content": question}],
            max_tokens=400,
        )
        reply = (
            "📝 Jawaban untuk dikirim ke volunteer:\n\n"
            f"{answer.strip()}\n\n"
            "_[Tap untuk copy & kirim ke volunteer]_"
        )
        if target_phone:
            normalized = self._normalize_phone(target_phone)
            reply += (
                f"\n\nMau langsung saya kirimkan ke {normalized}? "
                f"Balas:\n`/send {normalized}: {answer.strip()[:60]}...`"
            )
        return reply

    async def _handle_send(self, target_phone: str, text_to_send: str) -> str:
        """DM a volunteer on behalf of the fasilitator."""
        if not text_to_send:
            return "Format: `/send 628xxxxxxxxx: [pesan]`"
        normalized = self._normalize_phone(target_phone)
        if not normalized:
            return f"Nomor `{target_phone}` tidak valid."

        from backend.channels.whatsapp_handler import WhatsAppHandler

        try:
            sent = await WhatsAppHandler().send_message(normalized, text_to_send)
        except Exception as exc:
            logger.error("send relay to %s failed: %s", normalized, exc)
            return f"❌ Gagal mengirim ke {normalized}: {exc}"
        if not sent:
            return (
                f"❌ Pesan ke {normalized} tidak terkirim. "
                "Cek token WA dan apakah nomor sudah diwhitelist di Meta dashboard."
            )
        preview = text_to_send if len(text_to_send) < 80 else text_to_send[:77] + "..."
        return (
            f"✅ Pesan terkirim ke {normalized}:\n_{preview}_"
        )

    # ------------------------------------------------------------------ #
    # Psychological guidance                                              #
    # ------------------------------------------------------------------ #

    _find_target_by_name = staticmethod(find_target_volunteer)

    async def _handle_psych_guidance(
        self, message: str, target: dict | None, fasilitator_tg_id: int | None
    ) -> str:
        """Generate empathetic, data-grounded guidance for handling a quitter."""
        context_block = self._build_psych_block(target)
        system_prompt = SYSTEM_PROMPT + PSYCH_GUIDANCE + context_block
        history = (
            await self.get_chat_history(fasilitator_tg_id, limit=6)
            if fasilitator_tg_id
            else []
        )
        messages = history + [{"role": "user", "content": message}]
        return await self.call_claude(
            system_prompt,
            messages,
            model=COMPLEX_MODEL,
            max_tokens=1500,
        )

    async def _handle_draft_message(self, target: dict | None) -> str:
        """Draft a ready-to-send WA message for the named volunteer."""
        if target is None:
            return (
                "Sebutkan nama volunteer yang mau dikirim pesannya ya. "
                "Contoh: 'draftkan pesan untuk Rizki'."
            )
        context_block = self._build_psych_block(target)
        system_prompt = SYSTEM_PROMPT + DRAFT_GUIDANCE + context_block
        prompt = (
            f"Tulis draft pesan untuk {target.get('name')}. "
            "Gunakan data progress + riwayat chat di context untuk personalisasi."
        )
        draft = await self.call_claude(
            system_prompt,
            [{"role": "user", "content": prompt}],
            model=COMPLEX_MODEL,
            max_tokens=400,
        )
        phone = target.get("phone")
        send_hint = (
            f"\n\n_Balas:_ `/send {phone}: {draft.strip()[:60]}...`"
            if phone
            else ""
        )
        return (
            f"✉️ Draft untuk {target.get('name')}:\n\n"
            f"{draft.strip()}\n\n"
            "_[Edit jika perlu, lalu copy ke chat volunteer]_"
            f"{send_hint}"
        )

    def _build_psych_block(self, target: dict | None) -> str:
        """Assemble the volunteer-specific data block for psych/draft prompts."""
        if target is None:
            return (
                "\n\n=== KONTEKS VOLUNTEER ===\n"
                "Volunteer spesifik tidak terdeteksi dari pesan. Berikan "
                "rekomendasi umum + minta fasilitator menyebut nama untuk "
                "personalisasi lebih dalam."
            )

        target_id = target.get("id")
        target_tg = target.get("telegram_id")

        reports = (
            db.table("reports")
            .select("kg_collected, reported_at, photo_url, verified, is_flagged")
            .eq("volunteer_id", target_id)
            .order("reported_at", desc=True)
            .execute()
            .data
            or []
        )
        total_kg = sum(float(r.get("kg_collected") or 0) for r in reports)
        quota = float(target.get("quota_kg") or 0)
        pct = (total_kg / quota * 100) if quota else 0

        first_report = reports[-1]["reported_at"] if reports else None
        days_active = self._days_since(first_report)

        since_iso = (
            (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        )
        recent_chats: list[dict] = []
        if target_tg:
            try:
                recent_chats = (
                    db.table("chat_history")
                    .select("role, content, created_at")
                    .eq("telegram_id", target_tg)
                    .gte("created_at", since_iso)
                    .order("created_at", desc=True)
                    .limit(20)
                    .execute()
                    .data
                    or []
                )
            except Exception as exc:
                logger.warning(
                    "psych chat_history read failed for %s: %s", target_tg, exc
                )

        chat_lines = (
            "\n".join(
                f"- [{r.get('created_at', '')[:16]}] {r.get('role')}: "
                f"{(r.get('content') or '')[:200]}"
                for r in reversed(recent_chats)
            )
            or "(tidak ada chat 7 hari terakhir, atau volunteer WhatsApp tanpa riwayat tersimpan)"
        )

        quit_signal_count = sum(
            1
            for r in recent_chats
            if r.get("role") == "user"
            and any(kw in (r.get("content") or "").lower() for kw in AT_RISK_KEYWORDS)
        )

        return (
            "\n\n=== KONTEKS VOLUNTEER ===\n"
            f"Nama: {target.get('name')}\n"
            f"Area: {target.get('area', '-')}\n"
            f"Kuota: {quota:g} kg | Terkumpul: {total_kg:g} kg ({pct:.0f}%)\n"
            f"Jumlah laporan: {len(reports)}\n"
            f"Aktif sejak: {days_active} hari (laporan pertama: "
            f"{first_report[:10] if first_report else 'belum ada'})\n"
            f"Sinyal mau berhenti dalam riwayat: {quit_signal_count}x\n"
            "\nRiwayat chat 7 hari terakhir (oldest → newest):\n"
            f"{chat_lines}"
        )

    _days_since = staticmethod(_shared_days_since)

    # ------------------------------------------------------------------ #
    # Project context store                                               #
    # ------------------------------------------------------------------ #

    def _capture_project_context(self, message: str) -> str | None:
        """If ``message`` declares the project context, persist it and ack.

        Returns the canned acknowledgement when something was saved, or
        ``None`` so the caller can fall through to normal handling.
        """
        for pattern in PROJECT_CONTEXT_PATTERNS:
            match = pattern.search(message.strip())
            if not match:
                continue
            description = match.group(1).strip()
            if not description:
                continue
            try:
                db.table("fasilitator_context").upsert(
                    {"key": "project_description", "value": description},
                    on_conflict="key",
                ).execute()
            except Exception as exc:
                logger.error("Failed to persist project context: %s", exc)
                return (
                    "Aku belum bisa simpan konteks project (table belum siap). "
                    "Pastikan migrasi `fasilitator_context` sudah dijalankan ya."
                )
            preview = description if len(description) < 120 else description[:117] + "..."
            return f"✅ Konteks project disimpan:\n_{preview}_"
        return None

    @staticmethod
    def _load_project_context() -> str | None:
        try:
            rows = (
                db.table("fasilitator_context")
                .select("value")
                .eq("key", "project_description")
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception:
            return None
        return rows[0]["value"] if rows else None

    # ------------------------------------------------------------------ #
    # Strategy data block                                                 #
    # ------------------------------------------------------------------ #

    async def _build_strategy_block(
        self, volunteers: list[dict], telegram_id: int | None
    ) -> str:
        """Aggregate program stats + last 10 chat lines for the strategy prompt."""
        reports = (
            db.table("reports")
            .select("volunteer_id, kg_collected, location, photo_url, verified")
            .execute()
            .data
            or []
        )
        total_kg = sum(float(r.get("kg_collected") or 0) for r in reports)
        target_kg = sum(float(v.get("quota_kg") or 0) for v in volunteers)
        pct = (total_kg / target_kg * 100) if target_kg else 0

        kg_by_volunteer: dict[str, float] = defaultdict(float)
        for r in reports:
            kg_by_volunteer[r["volunteer_id"]] += float(r.get("kg_collected") or 0)

        names_by_id = {v["id"]: v.get("name") or "(tanpa nama)" for v in volunteers}
        active_ids = {v["id"] for v in volunteers if v.get("is_active", True)}

        ranked = sorted(
            ((vid, kg) for vid, kg in kg_by_volunteer.items() if vid in names_by_id),
            key=lambda kv: kv[1],
            reverse=True,
        )
        top_3 = [(names_by_id[vid], kg) for vid, kg in ranked[:3]]
        # Bottom: include active volunteers with low totals (treat missing as 0)
        low_pool = [
            (names_by_id[v["id"]], kg_by_volunteer.get(v["id"], 0))
            for v in volunteers
            if v["id"] in active_ids
        ]
        low_pool.sort(key=lambda kv: kv[1])
        bottom_3 = low_pool[:3]

        kg_by_area: dict[str, float] = defaultdict(float)
        for r in reports:
            location = (r.get("location") or "unknown")
            kg_by_area[location] += float(r.get("kg_collected") or 0)
        ranked_areas = sorted(kg_by_area.items(), key=lambda kv: kv[1], reverse=True)
        best_area = ranked_areas[0] if ranked_areas else ("-", 0)
        worst_area = ranked_areas[-1] if ranked_areas else ("-", 0)

        unique_reporters = len(kg_by_volunteer)
        avg_reports = (
            round(len(reports) / unique_reporters, 2) if unique_reporters else 0
        )
        photo_pct = (
            round(
                sum(1 for r in reports if r.get("photo_url")) / len(reports) * 100, 1
            )
            if reports
            else 0
        )

        at_risk = self._count_at_risk_volunteers()
        last_messages = await self.get_chat_history(telegram_id, limit=10) if telegram_id else []
        history_lines = (
            "\n".join(f"- {m['role']}: {m['content'][:160]}" for m in last_messages)
            or "(belum ada riwayat)"
        )

        project_context = self._load_project_context()
        project_line = (
            f"Deskripsi project (di-set fasilitator): {project_context}"
            if project_context
            else "Deskripsi project: (belum di-set; fasilitator bisa kirim "
            "'project kita ini adalah …')"
        )

        top_str = (
            ", ".join(f"{name} ({kg:g}kg)" for name, kg in top_3) or "-"
        )
        bottom_str = (
            ", ".join(f"{name} ({kg:g}kg)" for name, kg in bottom_3) or "-"
        )

        return (
            "\n\n=== DATA PROGRAM UNTUK ANALISIS STRATEGI ===\n"
            f"{project_line}\n"
            f"Total progress: {total_kg:g}/{target_kg:g} kg ({pct:.1f}%)\n"
            f"Volunteer teraktif: {top_str}\n"
            f"Volunteer paling pasif: {bottom_str}\n"
            f"Area terbaik: {best_area[0]} ({best_area[1]:g} kg)\n"
            f"Area terlemah: {worst_area[0]} ({worst_area[1]:g} kg)\n"
            f"Rata-rata laporan per volunteer: {avg_reports}\n"
            f"Persentase laporan dengan foto: {photo_pct}%\n"
            f"Volunteer yang pernah express mau berhenti: {at_risk} orang\n"
            f"\nRiwayat chat fasilitator terkini:\n{history_lines}"
        )

    @staticmethod
    def _count_at_risk_volunteers() -> int:
        """Distinct telegram_ids whose user-side chat history hints at quitting."""
        try:
            rows = (
                db.table("chat_history")
                .select("telegram_id, content")
                .eq("role", "user")
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning("Could not read chat_history for at-risk scan: %s", exc)
            return 0
        flagged: set = set()
        for row in rows:
            content = (row.get("content") or "").lower()
            if any(kw in content for kw in AT_RISK_KEYWORDS):
                flagged.add(row.get("telegram_id"))
        return len(flagged)

    # ------------------------------------------------------------------ #
    # Phase 6 — intent classifier + suggestions                          #
    # ------------------------------------------------------------------ #

    async def _classify_command(self, message: str) -> str:
        """Sonnet-classified command label; ``default`` for free-form chat."""
        if not message or not message.strip():
            return "default"
        verdict = await self.call_claude(
            INTENT_CLASSIFY_PROMPT,
            [{"role": "user", "content": message}],
            model=COMPLEX_MODEL,
            max_tokens=10,
        )
        label = (verdict or "").strip().lower().split()[0:1]
        candidate = label[0] if label else "default"
        candidate = candidate.replace("`", "").replace("'", "").replace('"', "")
        return candidate if candidate in FAS_INTENTS else "default"

    @staticmethod
    def _append_suggestions(reply: str, intent: str) -> str:
        opts = SUGGESTIONS.get(intent, SUGGESTIONS["default"])
        bullets = "\n".join(f"• {o}" for o in opts[:3])
        sep = "" if reply.endswith("\n") else "\n"
        return f"{reply}{sep}\n💡 Mau lanjut:\n{bullets}"

    async def _dispatch_intent(
        self, intent: str, message: str, context: dict
    ) -> str:
        handlers = {
            "send_reminder": lambda: self._handle_send_reminder_free(message),
            "get_status": lambda: self._handle_get_status(),
            "get_analytics": lambda: self._handle_get_analytics(message, context),
            "create_mission": lambda: self._handle_create_mission(message),
            "assign_volunteer": lambda: self._handle_assign_volunteer(message),
            "broadcast": lambda: self._handle_broadcast(message),
            "flag_review": lambda: self._handle_flag_review(),
            "generate_report": lambda: self._handle_generate_report(message, context),
            "generate_content": lambda: self._handle_generate_content(message, context),
            "get_volunteer_detail": lambda: self._handle_get_volunteer_detail(message),
            "query_other_volunteer": lambda: self._handle_query_other_volunteer(message),
        }
        return await handlers[intent]()

    # ------------------------------------------------------------------ #
    # /remind slash + free-text send_reminder                             #
    # ------------------------------------------------------------------ #

    async def _handle_remind_slash(
        self, *, subtype: str | None, arg: str, only_non_reporters: bool = False
    ) -> str:
        rows = (
            db.table("volunteers")
            .select("id, name, area, quota_kg, phone, telegram_id")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        if not rows:
            return "Belum ada volunteer aktif untuk dikirimi reminder."

        if only_non_reporters:
            today_start = (
                datetime.now(timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )
            reports_today = (
                db.table("reports")
                .select("volunteer_id")
                .gte("reported_at", today_start)
                .execute()
                .data
                or []
            )
            reported_ids = {r["volunteer_id"] for r in reports_today}
            rows = [v for v in rows if v["id"] not in reported_ids]
            if not rows:
                return (
                    "✅ Semua volunteer sudah lapor hari ini — "
                    "tidak ada reminder yang dikirim."
                )

        kind = subtype or "custom"
        recipients_named: list[str] = []
        for v in rows:
            reported_kg = self._sum_reports_for(v["id"])
            text = self._format_reminder_text(
                kind=kind,
                arg=arg,
                name=v.get("name") or "Volunteer",
                area=v.get("area") or "-",
                quota_kg=float(v.get("quota_kg") or 0),
                reported_kg=reported_kg,
            )
            await self._notify_volunteer_dict(v, text)
            recipients_named.append(v.get("name") or "?")
        return (
            f"✅ Reminder ({kind}) dikirim ke {len(rows)} volunteer: "
            + ", ".join(recipients_named)
        )

    async def _handle_send_reminder_free(self, message: str) -> str:
        """Free-text reminder routing (no slash). Defaults to progress reminder.

        When the fasilitator scopes the request to "yang belum lapor" we
        filter recipients to volunteers without a report today.
        """
        lowered = message.lower()
        only_non_reporters = (
            "belum lapor" in lowered
            or "belum report" in lowered
            or "yang belum" in lowered
        )
        return await self._handle_remind_slash(
            subtype="progress",
            arg=message,
            only_non_reporters=only_non_reporters,
        )

    @staticmethod
    def _format_reminder_text(
        *,
        kind: str,
        arg: str,
        name: str,
        area: str,
        quota_kg: float,
        reported_kg: float,
    ) -> str:
        template = REMIND_TEMPLATES.get(kind, REMIND_TEMPLATES["custom"])
        return template.format(
            name=name,
            arg=arg or "—",
            area=area,
            quota_kg=quota_kg,
            reported_kg=reported_kg,
        )

    @staticmethod
    def _sum_reports_for(volunteer_id: str) -> float:
        rows = (
            db.table("reports")
            .select("kg_collected")
            .eq("volunteer_id", volunteer_id)
            .execute()
            .data
            or []
        )
        return sum(float(r.get("kg_collected") or 0) for r in rows)

    @staticmethod
    async def _notify_volunteer_dict(volunteer: dict, text: str) -> None:
        from backend.agents.services.notifications import notify_volunteer

        await notify_volunteer(volunteer, text)

    # ------------------------------------------------------------------ #
    # Status / analytics / flag review                                    #
    # ------------------------------------------------------------------ #

    async def _handle_get_status(self) -> str:
        volunteers = (
            db.table("volunteers")
            .select("id, name, area")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        reports_today = (
            db.table("reports")
            .select("volunteer_id, kg_collected, location")
            .gte("reported_at", today_start)
            .execute()
            .data
            or []
        )
        kg_total_today = sum(
            float(r.get("kg_collected") or 0) for r in reports_today
        )
        reporters_today = {r["volunteer_id"] for r in reports_today}
        non_reporters = [
            v.get("name", "?")
            for v in volunteers
            if v["id"] not in reporters_today
        ]
        flagged = (
            db.table("reports")
            .select("id")
            .eq("is_flagged", True)
            .eq("verified", False)
            .execute()
            .data
            or []
        )
        locations = sorted({(r.get("location") or "").strip() for r in reports_today if r.get("location")})

        return (
            "📊 Status program hari ini:\n"
            f"📦 Total: {kg_total_today:g} kg\n"
            f"✅ Sudah lapor: {len(reporters_today)}/{len(volunteers)}\n"
            f"⚠️ Belum lapor: {', '.join(non_reporters[:10]) or '-'}\n"
            f"🚩 Laporan flagged (perlu review): {len(flagged)}\n"
            f"📍 Area aktif: {', '.join(locations) or '-'}"
        )

    async def _handle_get_analytics(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.impact_analyzer import ImpactAnalyzerAgent

        return await ImpactAnalyzerAgent().process(message, context)

    async def _handle_flag_review(self) -> str:
        rows = (
            db.table("reports")
            .select(
                "id, kg_collected, location, flag_reason, reported_at, "
                "volunteer_id"
            )
            .eq("is_flagged", True)
            .eq("verified", False)
            .order("reported_at", desc=True)
            .execute()
            .data
            or []
        )
        if not rows:
            return "✅ Tidak ada laporan flagged yang perlu direview saat ini."

        names = self._fetch_names_for(
            [r["volunteer_id"] for r in rows if r.get("volunteer_id")]
        )
        lines = []
        for r in rows[:10]:
            name = names.get(r.get("volunteer_id"), "?")
            kg = float(r.get("kg_collected") or 0)
            loc = r.get("location") or "-"
            reason = r.get("flag_reason") or "tidak ada alasan tercatat"
            lines.append(f"• {name}: {kg:g} kg @ {loc} — {reason}")
        return (
            f"🚩 Laporan flagged ({len(rows)} total, tampilkan 10 teratas):\n"
            + "\n".join(lines)
            + "\n\nApakah ingin saya approve atau reject? Sebutkan ID atau nama."
        )

    @staticmethod
    def _fetch_names_for(ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        rows = (
            db.table("volunteers")
            .select("id, name")
            .in_("id", ids)
            .execute()
            .data
            or []
        )
        return {r["id"]: r.get("name") or "?" for r in rows}

    # ------------------------------------------------------------------ #
    # Broadcast                                                            #
    # ------------------------------------------------------------------ #

    async def _handle_broadcast(self, message: str) -> str:
        # Extract the broadcast text — drop leading "broadcast", "umumkan", etc.
        text = re.sub(
            r"^(broadcast|umumkan(?:\s+ke\s+semua)?|kirim\s+ke\s+semua)[:,]?\s*",
            "",
            message.strip(),
            flags=re.IGNORECASE,
        )
        if not text or len(text) < 5:
            return "Broadcast tidak terkirim. Ketik: 'broadcast: <pesan>' (minimum 5 karakter)."
        rows = (
            db.table("volunteers")
            .select("id, name, phone, telegram_id")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        if not rows:
            return "Belum ada volunteer aktif sebagai penerima broadcast."
        for v in rows:
            await self._notify_volunteer_dict(v, text)
        return f"📢 Broadcast terkirim ke {len(rows)} volunteer."

    # ------------------------------------------------------------------ #
    # Create mission / assign volunteer                                   #
    # ------------------------------------------------------------------ #

    _MISSION_EXTRACT_PROMPT = (
        "Dari pesan fasilitator, ekstrak metadata misi baru sebagai JSON valid "
        "dengan kunci: title (string), description (string boleh kosong), "
        "deadline (ISO date YYYY-MM-DD jika ada, else null), quota_kg (number "
        "jika ada, else null). Balas HANYA JSON. Tidak ada teks lain."
    )

    async def _handle_create_mission(self, message: str) -> str:
        import json as _json

        try:
            raw = await self.call_claude(
                self._MISSION_EXTRACT_PROMPT,
                [{"role": "user", "content": message}],
                model=COMPLEX_MODEL,
                max_tokens=200,
            )
            payload_match = re.search(r"\{.*\}", raw, re.DOTALL)
            payload = _json.loads(payload_match.group(0)) if payload_match else {}
        except Exception as exc:
            logger.warning("create_mission extract failed: %s", exc)
            payload = {}

        title = (payload.get("title") or "").strip()
        if not title:
            return (
                "Aku butuh judul misi yang jelas. Contoh: 'buat misi "
                "pengumpulan PET di Cikini sampai 30 Juli, kuota 20 kg.'"
            )

        row = {
            "title": title,
            "description": payload.get("description") or "",
            "status": "active",
        }
        deadline = payload.get("deadline")
        if deadline:
            row["deadline"] = deadline

        try:
            inserted = (
                db.table("missions").insert(row).execute().data or []
            )
        except Exception as exc:
            return f"Gagal membuat misi: {exc}"

        if not inserted:
            return "Gagal membuat misi (tidak ada baris dikembalikan)."
        mid = inserted[0]["id"]
        return (
            f"✅ Misi '{title}' dibuat (id={mid[:8]}...). "
            "Tambahkan assignment volunteer dengan: 'tugaskan <nama> ke "
            f"{title}'."
        )

    _ASSIGN_EXTRACT_PROMPT = (
        "Dari pesan fasilitator, ekstrak data assignment sebagai JSON: "
        "{volunteer_name: string, mission_title_or_area: string, "
        "quota_kg: number atau null}. Balas hanya JSON."
    )

    async def _handle_assign_volunteer(self, message: str) -> str:
        import json as _json

        try:
            raw = await self.call_claude(
                self._ASSIGN_EXTRACT_PROMPT,
                [{"role": "user", "content": message}],
                model=COMPLEX_MODEL,
                max_tokens=160,
            )
            payload_match = re.search(r"\{.*\}", raw, re.DOTALL)
            payload = _json.loads(payload_match.group(0)) if payload_match else {}
        except Exception as exc:
            logger.warning("assign extract failed: %s", exc)
            payload = {}

        volunteer_name = (payload.get("volunteer_name") or "").strip()
        mission_hint = (payload.get("mission_title_or_area") or "").strip()
        if not volunteer_name or not mission_hint:
            return (
                "Aku butuh nama volunteer + nama misi/area target. Contoh: "
                "'tugaskan Budi ke misi PET Cikini'."
            )

        vol_rows = (
            db.table("volunteers")
            .select("id, name")
            .ilike("name", f"%{volunteer_name}%")
            .execute()
            .data
            or []
        )
        if not vol_rows:
            return f"Volunteer '{volunteer_name}' tidak ditemukan."
        if len(vol_rows) > 1:
            names = ", ".join(v["name"] for v in vol_rows)
            return f"Ada beberapa volunteer cocok: {names}. Sebutkan nama lengkap."
        volunteer = vol_rows[0]

        mission_rows = (
            db.table("missions")
            .select("id, title")
            .ilike("title", f"%{mission_hint}%")
            .eq("status", "active")
            .execute()
            .data
            or []
        )
        if not mission_rows:
            return f"Misi yang cocok dengan '{mission_hint}' tidak ditemukan."
        mission = mission_rows[0]

        quota_kg = payload.get("quota_kg")
        row = {
            "volunteer_id": volunteer["id"],
            "mission_id": mission["id"],
            "assigned_area": mission_hint,
        }
        if quota_kg:
            row["quota_kg"] = quota_kg

        try:
            db.table("volunteer_missions").insert(row).execute()
        except Exception as exc:
            return f"Assignment gagal: {exc}"

        suffix = f" (kuota {quota_kg:g} kg)" if quota_kg else ""
        return (
            f"✅ {volunteer['name']} ditugaskan ke misi '{mission['title']}'"
            f"{suffix}."
        )

    # ------------------------------------------------------------------ #
    # Volunteer detail / query                                            #
    # ------------------------------------------------------------------ #

    async def _handle_get_volunteer_detail(self, message: str) -> str:
        return await self.handle_volunteer_query(message, {"is_fasilitator": True})

    async def _handle_query_other_volunteer(self, message: str) -> str:
        return await self.handle_volunteer_query(message, {"is_fasilitator": True})

    # ------------------------------------------------------------------ #
    # Public cross-volunteer query handler                                #
    # ------------------------------------------------------------------ #

    async def handle_volunteer_query(
        self, message: str, context: dict
    ) -> str:
        """Cross-volunteer query entry point — respects peer-query policy."""
        from backend.utils.volunteer_resolver import (
            VolunteerResolver,
            can_query_volunteer,
        )

        resolver = VolunteerResolver(db, llm_caller=self.call_claude)
        targets = await resolver.extract_volunteer_mentions(message)

        # Filter targets the requester is allowed to see.
        requester_volunteer = context.get("volunteer") or {}
        requester_id = requester_volunteer.get("id")
        allowed: list[dict] = []
        denied: list[str] = []
        for target in targets:
            if can_query_volunteer(
                requester_id=requester_id,
                target_volunteer=target,
                context=context,
            ):
                allowed.append(target)
            else:
                denied.append(target.get("name") or "?")

        if denied and not allowed:
            return (
                "Hanya fasilitator yang bisa melihat data volunteer lain. "
                "Untuk lihat data kamu sendiri, tanyakan 'progress saya' "
                "atau 'apa tugas saya'."
            )

        if not allowed:
            if "siapa" in message.lower() and "lapor" in message.lower():
                return await self._handle_get_status()
            return (
                "Maksudnya volunteer yang mana? Sebutkan nama atau @username "
                "supaya saya bisa bantu."
            )

        full_view = bool(context.get("is_fasilitator"))
        if len(allowed) == 1:
            return self._format_volunteer_query_single(
                allowed[0], full_view=full_view
            )
        return self._format_volunteer_query_multi(
            allowed, full_view=full_view
        )

    # ------------------------------------------------------------------ #
    # Cross-volunteer formatters                                          #
    # ------------------------------------------------------------------ #

    def _format_volunteer_query_single(
        self, volunteer: dict, *, full_view: bool
    ) -> str:
        total = self._sum_reports_for(volunteer["id"])
        quota = float(volunteer.get("quota_kg") or 0)
        pct = (total / quota * 100) if quota else 0

        if not full_view:
            return (
                f"📋 Info volunteer: {volunteer.get('name')}\n"
                f"📍 Area: {volunteer.get('area') or '-'}\n"
                f"📦 Progress: {pct:.0f}% (dari kuota)"
            )

        mission = self._active_mission_for(volunteer["id"])
        deadline = (mission or {}).get("deadline") or "-"
        days_left = self._days_left_to(deadline)
        last_report = self._last_report_for(volunteer["id"])
        last_line = (
            f"{last_report['reported_at'][:10]} — "
            f"{float(last_report['kg_collected']):g} kg di "
            f"{last_report.get('location') or '-'}"
            if last_report
            else "(belum ada laporan)"
        )
        team = volunteer.get("team") or []
        team_str = ", ".join(team) if team else "-"
        status_emoji, status_text = self._status_for_pct(pct)

        return (
            f"📋 Info volunteer: {volunteer.get('name')}\n"
            f"📍 Area: {volunteer.get('area') or '-'}\n"
            f"🎯 Kuota: {quota:g} kg\n"
            f"📦 Progress: {total:g}/{quota:g} kg ({pct:.0f}%)\n"
            f"⏰ Deadline: {deadline} ({days_left} hari lagi)\n"
            f"👥 Tim: {team_str}\n"
            f"📝 Laporan terakhir: {last_line}\n"
            f"Status: {status_emoji} {status_text}"
        )

    def _format_volunteer_query_multi(
        self, volunteers: list[dict], *, full_view: bool
    ) -> str:
        names = " vs ".join(v.get("name") or "?" for v in volunteers)
        lines = [f"📊 Progress {names}:"]
        for v in volunteers:
            total = self._sum_reports_for(v["id"])
            quota = float(v.get("quota_kg") or 0)
            pct = (total / quota * 100) if quota else 0
            if full_view:
                lines.append(
                    f"• {v.get('name')}: {total:g}/{quota:g} kg "
                    f"({pct:.0f}%) — {v.get('area') or '-'}"
                )
            else:
                lines.append(
                    f"• {v.get('name')}: {pct:.0f}% — {v.get('area') or '-'}"
                )
        return "\n".join(lines)

    @staticmethod
    def _active_mission_for(volunteer_id: str) -> dict | None:
        rows = (
            db.table("volunteer_missions")
            .select("quota_kg, assigned_area, missions(*)")
            .eq("volunteer_id", volunteer_id)
            .execute()
            .data
            or []
        )
        for row in rows:
            m = row.get("missions") or {}
            if m.get("status") == "active":
                return m
        return None

    @staticmethod
    def _last_report_for(volunteer_id: str) -> dict | None:
        rows = (
            db.table("reports")
            .select("kg_collected, location, reported_at")
            .eq("volunteer_id", volunteer_id)
            .order("reported_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    @staticmethod
    def _days_left_to(deadline: str | None) -> int:
        if not deadline:
            return 0
        try:
            dt = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            return max((dt - datetime.now(timezone.utc)).days, 0)
        except Exception:
            return 0

    @staticmethod
    def _status_for_pct(pct: float) -> tuple[str, str]:
        if pct >= 100:
            return "🎉", "Selesai"
        if pct >= 75:
            return "🔥", "Hampir selesai"
        if pct >= 50:
            return "💪", "Setengah jalan"
        if pct > 0:
            return "🚀", "Sudah mulai"
        return "⚪", "Belum mulai"

    def _find_volunteer_in_message(self, message: str) -> dict | None:
        candidates = (
            db.table("volunteers")
            .select("id, name, area, quota_kg, phone, telegram_id")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        return self._find_target_by_name(message, candidates)

    def _format_volunteer_detail(
        self, volunteer: dict, *, brief: bool = False
    ) -> str:
        total = self._sum_reports_for(volunteer["id"])
        quota = float(volunteer.get("quota_kg") or 0)
        pct = (total / quota * 100) if quota else 0
        rows = (
            db.table("reports")
            .select("kg_collected, location, reported_at")
            .eq("volunteer_id", volunteer["id"])
            .order("reported_at", desc=True)
            .limit(3)
            .execute()
            .data
            or []
        )
        last_lines = (
            "\n".join(
                f"  • {r.get('reported_at', '')[:10]}: "
                f"{float(r['kg_collected']):g} kg @ {r.get('location') or '-'}"
                for r in rows
            )
            or "  (belum ada laporan)"
        )
        head = (
            f"👤 {volunteer.get('name')}\n"
            f"📍 Area: {volunteer.get('area') or '-'}\n"
            f"📦 Progress: {total:g}/{quota:g} kg ({pct:.0f}%)"
        )
        if brief:
            return head
        return f"{head}\n📅 Laporan terakhir:\n{last_lines}"

    # ------------------------------------------------------------------ #
    # Report / content delegation                                         #
    # ------------------------------------------------------------------ #

    async def _handle_generate_report(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.impact_analyzer import ImpactAnalyzerAgent

        return await ImpactAnalyzerAgent().process(message, context)

    async def _handle_generate_content(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.content_creator import ContentCreatorAgent

        return await ContentCreatorAgent().process(message, context)

    # ------------------------------------------------------------------ #
    # Scheduled morning briefing                                          #
    # ------------------------------------------------------------------ #

    async def get_morning_briefing(self) -> str:
        from backend.agents.services.notifications import alert_fasilitator

        volunteers = (
            db.table("volunteers")
            .select("id, name")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        yesterday_start = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        reports_yest = (
            db.table("reports")
            .select("volunteer_id, kg_collected")
            .gte("reported_at", yesterday_start)
            .lt("reported_at", today_start)
            .execute()
            .data
            or []
        )
        kg_yest = sum(float(r.get("kg_collected") or 0) for r in reports_yest)
        reporters_yest = {r["volunteer_id"] for r in reports_yest}
        non_reporters = [
            v.get("name", "?")
            for v in volunteers
            if v["id"] not in reporters_yest
        ]

        program_total = sum(
            float(r.get("kg_collected") or 0)
            for r in (
                db.table("reports").select("kg_collected").execute().data or []
            )
        )
        target_kg = sum(
            float(r.get("quota_kg") or 0)
            for r in (
                db.table("volunteer_missions")
                .select("quota_kg")
                .execute()
                .data
                or []
            )
        )
        pct = (program_total / target_kg * 100) if target_kg else 0

        flagged = (
            db.table("reports")
            .select("id")
            .eq("is_flagged", True)
            .eq("verified", False)
            .execute()
            .data
            or []
        )

        non_rep_str = (
            ", ".join(non_reporters[:6])
            + (f" +{len(non_reporters) - 6} lainnya" if len(non_reporters) > 6 else "")
            if non_reporters
            else "(semua sudah lapor 🎉)"
        )

        active_missions = (
            db.table("missions")
            .select("title, deadline")
            .eq("status", "active")
            .execute()
            .data
            or []
        )
        now = datetime.now(timezone.utc)
        deadline_lines: list[str] = []
        for m in active_missions:
            raw = m.get("deadline")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            days_left = max((dt - now).days, 0)
            deadline_lines.append(
                f"  • {m.get('title') or 'Misi'}: {days_left} hari lagi"
            )
        deadline_block = (
            "\n⏰ Deadline misi aktif:\n" + "\n".join(deadline_lines)
            if deadline_lines
            else ""
        )

        briefing = (
            "🌅 Morning briefing:\n"
            f"📦 Total terkumpul (program): {program_total:g} kg "
            f"({pct:.0f}% dari target {target_kg:g} kg)\n"
            f"📈 Kemarin: {kg_yest:g} kg dari {len(reporters_yest)} volunteer\n"
            f"✅ Sudah lapor kemarin: {len(reporters_yest)}/{len(volunteers)} "
            "volunteer\n"
            f"⚠️ Perlu perhatian: {len(flagged)} laporan flagged\n"
            f"🔔 Belum lapor: {non_rep_str}"
            f"{deadline_block}"
        )
        await alert_fasilitator(briefing)
        return briefing
