"""Consultation mixin: Q&A relay, psych/draft guidance, strategy + project context."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from backend.database.supabase_client import db
from backend.utils.date_utils import days_since as _shared_days_since

from ..base_agent import COMPLEX_MODEL
from ..prompts.fasilitator_hub import (
    DRAFT_GUIDANCE,
    PSYCH_GUIDANCE,
    STRATEGY_GUIDANCE,
    SYSTEM_PROMPT,
)
from ._constants import AT_RISK_KEYWORDS, PROJECT_CONTEXT_PATTERNS, QA_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class ConsultMixin:
    """Strategic consultation, empathetic guidance, drafting, and Q&A relay."""

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
