"""Reminder mixin: action-item reminder draft → approval → scheduling.

Triggered when the fasilitator asks for a reminder in free text
("buatkan reminder presensi", "ingetin volunteer isi pre-test"). The flow:

1. Detect the reminder *type* from the message.
2. Resolve the specific ``action_items`` row (exact → partial → semantic).
3. Generate an on-persona draft via :class:`ReminderGenerator`.
4. Show the draft + scheduling options and park it in pending state.
5. On a 'kirim…' reply, ``ScheduleParser`` decides the send time and the
   reminder is sent now (immediate) or stashed in ``scheduled_messages`` for
   the every-minute dispatch job.

Mirrors the Step 6.1 relay draft flow: pending state keyed per channel,
edit/cancel handling, single-turn resume in :meth:`_resume_reminder_draft`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Pending-state step label for a parked reminder draft awaiting approval.
REMINDER_DRAFT_STEP = "reminder_draft_pending"

_DEFAULT_DELAY_HOURS = 8

# Connectives that join multiple action items in one combine request, e.g.
# "reminder kelas Sabtu sekalian pretest" / "presensi + post-test".
_COMBINE_SPLIT = re.compile(
    r"\b(?:sekalian|plus|dan|sama|gabungkan|gabung|jadi\s+satu)\b|\+",
    re.IGNORECASE,
)

# Tokens stripped when extracting the action-item mention from the request.
_MENTION_STOPWORDS: frozenset[str] = frozenset(
    {
        "reminder", "ingetin", "ingatkan", "pengingat",
        "buatkan", "buat", "bikin", "kirim", "kirimkan",
        "volunteer", "relawan", "para", "semua", "ke",
        "isi", "baca", "buka", "kerjakan", "ikut", "hadir",
        "tolong", "dong", "ya", "yuk", "untuk", "soal", "tentang",
        "minggu", "hari", "ini", "nih", "si",
    }
)


class ReminderMixin:
    """Action-item reminder generation + approval + scheduling."""

    # ------------------------------------------------------------------ #
    # Detection                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_reminder_request(message: str) -> bool:
        """True when the message asks to build an action-item reminder.

        Slash ``/remind`` is handled elsewhere; this only matches free text.
        """
        from ._constants import REMINDER_REQUEST_KEYWORDS

        if not message or message.lstrip().startswith("/"):
            return False
        lowered = message.lower()
        return any(kw in lowered for kw in REMINDER_REQUEST_KEYWORDS)

    @staticmethod
    def _extract_mention(message: str) -> str:
        """Strip reminder verbs/filler to leave the action-item name phrase."""
        tokens = re.findall(r"[\w'-]+", (message or "").lower())
        kept = [t for t in tokens if t not in _MENTION_STOPWORDS]
        phrase = " ".join(kept).strip()
        return phrase or (message or "").strip()

    @classmethod
    def _is_combine_request(cls, message: str) -> bool:
        """True when the message links 2+ items ("kelas Sabtu sekalian pretest")."""
        return bool(message) and bool(_COMBINE_SPLIT.search(message))

    async def _resolve_multiple_items(self, resolver, message: str) -> list[dict]:
        """Split on combine connectives, resolve each segment, dedup by id."""
        segments = [s for s in _COMBINE_SPLIT.split(message) if s and s.strip()]
        found: dict = {}
        for segment in segments:
            mention = self._extract_mention(segment)
            if not mention:
                continue
            type_hint = await resolver.detect_type_from_message(segment)
            hit = await resolver.find_by_mention(mention, type_hint)
            if isinstance(hit, dict):  # skip None / ambiguous-list segments
                found[hit.get("id")] = hit
        return list(found.values())

    # ------------------------------------------------------------------ #
    # Step 1 — build the draft                                            #
    # ------------------------------------------------------------------ #

    async def _handle_reminder_request(self, message: str, context: dict) -> str:
        """Resolve the action item, generate a draft, and park it pending."""
        from backend.agents.reminder_generator import ReminderGenerator
        from backend.agents.services import pending_state as _pending_state
        from backend.database.supabase_client import db
        from backend.utils.action_item_resolver import ActionItemResolver

        resolver = ActionItemResolver(db, llm_caller=self.call_claude)

        # Combine attempt — opportunistic: only commits when 2+ DISTINCT items
        # resolve. False positives on connectives fall through to the single
        # path, so a "dan"/"sama" inside one item's name still works.
        if self._is_combine_request(message):
            try:
                items = await self._resolve_multiple_items(resolver, message)
            except Exception as exc:
                logger.warning("combine lookup failed: %s", exc)
                items = []
            if len(items) >= 2:
                persona = await self._load_persona()
                draft = await ReminderGenerator().generate_combined_draft(
                    items, persona
                )
                return await self._park_reminder_draft(
                    draft,
                    context=context,
                    action_item_id=items[0].get("id"),
                    type_="combined",
                    action_item_ids=[a.get("id") for a in items],
                )

        # Single path.
        mention = self._extract_mention(message)
        type_hint = await resolver.detect_type_from_message(message)
        try:
            item = await resolver.find_by_mention(mention, type_hint)
        except Exception as exc:
            logger.warning("action-item lookup failed: %s", exc)
            return (
                "Gagal mencari action item (apakah tabel `action_items` sudah "
                "ada di dashboard?). Coba lagi sebentar."
            )

        # No match → tell the fasilitator to add it first.
        if item is None:
            return (
                f"Action item '{mention}' belum ada di dashboard. "
                "Tambahkan dulu ya."
            )

        # Multiple matches → ask which one.
        if isinstance(item, list):
            titles = "\n".join(f"• {a.get('title', '?')}" for a in item[:8])
            return (
                f"Ada beberapa action item cocok '{mention}':\n{titles}\n\n"
                "Sebutkan judul lengkapnya ya."
            )

        persona = await self._load_persona()
        draft = await ReminderGenerator().generate_draft(item, persona)
        return await self._park_reminder_draft(
            draft,
            context=context,
            action_item_id=item.get("id"),
            type_=item.get("type"),
        )

    async def _park_reminder_draft(
        self,
        draft: str,
        *,
        context: dict,
        action_item_id,
        type_,
        action_item_ids: list | None = None,
    ) -> str:
        """Park a (single or combined) draft in pending state + show options."""
        from backend.agents.services import pending_state as _pending_state

        data = {
            "text": draft,
            "action_item_id": action_item_id,
            "type": type_,
            "target_filter": "all",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "revision_count": 0,
        }
        if action_item_ids is not None:
            data["action_item_ids"] = action_item_ids
        _pending_state.set_pending(
            _pending_state.pending_key(context), REMINDER_DRAFT_STEP, data
        )
        delay_hours = await self._reminder_delay_hours()
        return self._format_draft_reply(draft, delay_hours)

    @staticmethod
    def _format_draft_reply(draft: str, delay_hours: int) -> str:
        return (
            f"📝 DRAFT:\n{draft.strip()}\n\n"
            f"✅ 'kirim' → jadwalkan (default {delay_hours} jam)\n"
            "⏰ 'kirim 24 jam lagi' / 'kirim 6 Juli jam 7 malam' → waktu spesifik\n"
            "⚡ 'kirim sekarang' → langsung tanpa delay\n"
            "✏️ 'edit [instruksi]' → revisi\n"
            "❌ 'batal'"
        )

    # ------------------------------------------------------------------ #
    # Step 7 — resume on approval / edit / cancel                         #
    # ------------------------------------------------------------------ #

    async def _resume_reminder_draft(
        self, *, message: str, context: dict, entry: dict
    ) -> str:
        """Handle a reply to a parked reminder draft."""
        from backend.agents.services import pending_state as _pending_state

        data = entry.get("data") or {}
        lowered = (message or "").strip().lower()
        key = _pending_state.pending_key(context)

        # Cancel.
        if lowered in {"batal", "cancel", "batalkan"} or lowered.startswith("batal"):
            _pending_state.store.pop(key, None)
            return "❌ Draft reminder dibatalkan."

        # Edit / revise.
        if lowered.startswith("edit"):
            instruction = message.strip()[4:].strip()
            if not instruction:
                return "Sebutkan revisinya, contoh: `edit bikin lebih singkat`."
            return await self._revise_reminder_draft(instruction, data, context)

        # Approve + schedule (any 'kirim…' variant or bare immediate words).
        if "kirim" in lowered or lowered in {"sekarang", "langsung"}:
            reply = await self._approve_and_schedule_reminder(data, message, context)
            _pending_state.store.pop(key, None)
            return reply

        # Anything else — re-show the options.
        delay_hours = await self._reminder_delay_hours()
        return (
            "Belum jelas. " + self._format_draft_reply(data.get("text", ""), delay_hours)
        )

    async def _revise_reminder_draft(
        self, instruction: str, data: dict, context: dict
    ) -> str:
        """Re-generate the draft applying the fasilitator's edit instruction."""
        from backend.agents.base_agent import COMPLEX_MODEL
        from backend.agents.services import pending_state as _pending_state

        old = (data.get("text") or "").strip()
        system_prompt = (
            "Revisi draft pesan reminder WhatsApp berikut sesuai instruksi "
            "fasilitator. Pertahankan placeholder {nama}. Singkat (maks 5-6 "
            "baris), hangat, jelas. Balas HANYA teks pesan barunya.\n\n"
            f"=== DRAFT LAMA ===\n{old}\n\n"
            f"=== INSTRUKSI ===\n{instruction}"
        )
        revised = await self.call_claude(
            system_prompt,
            [{"role": "user", "content": instruction}],
            model=COMPLEX_MODEL,
        )

        data = {
            **data,
            "text": revised,
            "revision_count": int(data.get("revision_count") or 0) + 1,
        }
        _pending_state.set_pending(
            _pending_state.pending_key(context), REMINDER_DRAFT_STEP, data
        )
        delay_hours = await self._reminder_delay_hours()
        return self._format_draft_reply(revised, delay_hours)

    # ------------------------------------------------------------------ #
    # Approval → send now or schedule                                     #
    # ------------------------------------------------------------------ #

    async def _approve_and_schedule_reminder(
        self, data: dict, message: str, context: dict
    ) -> str:
        """Decide the send time and either send now or stash for the scheduler."""
        from backend.agents.services.notifications import notify_volunteer
        from backend.infrastructure.composition_root import (
            build_scheduled_message_repository,
        )
        from backend.utils.schedule_parser import ScheduleParser
        from backend.utils.scheduler import _expand_recipients

        text = (data.get("text") or "").strip()
        target_filter = data.get("target_filter") or "all"
        schedule = await ScheduleParser(llm_caller=self.call_claude).parse_send_time(
            message
        )
        recipients = _expand_recipients(target_filter)

        # Immediate — send right away, personalising the {nama} placeholder.
        if schedule["mode"] == "immediate":
            sent = 0
            for volunteer in recipients:
                personal = text.replace("{nama}", volunteer.get("name") or "")
                try:
                    await notify_volunteer(volunteer, personal)
                    sent += 1
                except Exception as exc:
                    logger.warning(
                        "reminder send failed for %s: %s", volunteer.get("name"), exc
                    )
            return f"✅ Dikirim sekarang ke {sent} volunteer!"

        # Otherwise — schedule it for the dispatch job.
        try:
            await build_scheduled_message_repository().schedule_reminder(
                message_template=text,
                recipient_filter=target_filter,
                action_item_id=data.get("action_item_id"),
                scheduled_at=schedule["send_at"],
                created_by="fasilitator_reminder",
            )
        except Exception as exc:
            logger.warning("scheduled_messages insert failed: %s", exc)
            return (
                "Gagal menjadwalkan (apakah tabel `scheduled_messages` sudah "
                f"ada?). Error: {exc}"
            )

        return (
            "✅ Reminder dijadwalkan!\n\n"
            f"📤 Akan dikirim {schedule['label']}\n"
            f"👥 Ke {len(recipients)} volunteer\n\n"
            "Mau ubah? Ketik 'kirim sekarang' atau 'batalkan jadwal'."
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    async def _load_persona(self) -> dict:
        """Load persona settings from fasilitator context, with defaults."""
        from backend.infrastructure.composition_root import (
            build_fasilitator_context_repository,
        )

        repo = build_fasilitator_context_repository()
        try:
            agent_name = await repo.get("persona_agent_name")
            tone = await repo.get("persona_tone")
            use_emoji = await repo.get("persona_use_emoji")
        except Exception as exc:  # noqa: BLE001 — fall back to defaults
            logger.warning("persona load failed: %s", exc)
            agent_name = tone = use_emoji = None
        return {
            "agent_name": agent_name or "Asisten GBP",
            "tone": tone or "Kasual",
            "use_emoji": (use_emoji or "true").lower() != "false",
        }

    async def _reminder_delay_hours(self) -> int:
        """``reminder_delay_hours`` setting (default 8)."""
        from backend.infrastructure.composition_root import (
            build_fasilitator_context_repository,
        )

        try:
            raw = await build_fasilitator_context_repository().get(
                "reminder_delay_hours"
            )
            return int(raw) if raw else _DEFAULT_DELAY_HOURS
        except (ValueError, TypeError):
            return _DEFAULT_DELAY_HOURS
        except Exception as exc:  # noqa: BLE001
            logger.warning("reminder_delay_hours read failed: %s", exc)
            return _DEFAULT_DELAY_HOURS
