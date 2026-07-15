"""Command mixin: intent classify/dispatch, reminders, status, broadcast."""

import logging
import re

from ..base_agent import COMPLEX_MODEL
from ._constants import FAS_INTENTS, INTENT_CLASSIFY_PROMPT, REMIND_TEMPLATES, SUGGESTIONS

logger = logging.getLogger(__name__)


class CommandMixin:
    """Phase 6 intent classifier + the dedicated operational command handlers."""

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
            "assign_volunteer": lambda: self._handle_assign_volunteer(message),
            "broadcast": lambda: self._handle_broadcast(message),
            "generate_report": lambda: self._handle_generate_report(message, context),
            "generate_content": lambda: self._handle_generate_content(message, context),
            "get_volunteer_detail": lambda: self._handle_get_volunteer_detail(message),
            "query_other_volunteer": lambda: self._handle_query_other_volunteer(message),
            "save_report_for": lambda: self._handle_save_report_for(message, context),
        }
        return await handlers[intent]()

    # ------------------------------------------------------------------ #
    # /remind slash + free-text send_reminder                             #
    # ------------------------------------------------------------------ #

    async def _handle_remind_slash(
        self, *, subtype: str | None, arg: str
    ) -> str:
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        rows = await build_volunteer_query_repository().list_active()
        if not rows:
            return "Belum ada volunteer aktif untuk dikirimi reminder."

        kind = subtype or "custom"
        recipients_named: list[str] = []
        for v in rows:
            text = self._format_reminder_text(
                kind=kind,
                arg=arg,
                name=v.get("name") or "Volunteer",
            )
            await self._notify_volunteer_dict(v, text)
            recipients_named.append(v.get("name") or "?")
        return (
            f"✅ Reminder ({kind}) dikirim ke {len(rows)} volunteer: "
            + ", ".join(recipients_named)
        )

    async def _handle_send_reminder_free(self, message: str) -> str:
        """Free-text reminder routing (no slash) — sends the message as-is."""
        return await self._handle_remind_slash(subtype="custom", arg=message)

    @staticmethod
    def _format_reminder_text(*, kind: str, arg: str, name: str) -> str:
        template = REMIND_TEMPLATES.get(kind, REMIND_TEMPLATES["custom"])
        return template.format(name=name, arg=arg or "—")

    @staticmethod
    async def _notify_volunteer_dict(volunteer: dict, text: str) -> None:
        from backend.agents.services.notifications import notify_volunteer

        await notify_volunteer(volunteer, text)

    # ------------------------------------------------------------------ #
    # Status / analytics / flag review                                    #
    # ------------------------------------------------------------------ #

    async def _handle_get_status(self) -> str:
        from backend.database.supabase_client import db
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )
        from backend.utils.action_item_resolver import ActionItemResolver

        volunteers = await build_volunteer_query_repository().list_active()
        try:
            challenges = ActionItemResolver(db).list_active_challenges()
        except Exception:
            challenges = []

        if challenges:
            ch_lines = "\n".join(
                f"  • {c.get('title')}"
                + (
                    f" (deadline {str(c['deadline'])[:10]})"
                    if c.get("deadline")
                    else ""
                )
                for c in challenges
            )
        else:
            ch_lines = "  (belum ada challenge aktif)"

        return (
            "📊 Status program:\n"
            f"👥 Volunteer aktif: {len(volunteers)}\n"
            f"🎯 Challenge berjalan:\n{ch_lines}"
        )

    async def _handle_get_analytics(
        self, message: str, context: dict
    ) -> str:
        from backend.agents.impact_analyzer import ImpactAnalyzerAgent

        return await ImpactAnalyzerAgent().process(message, context)

    async def _handle_flag_review(self) -> str:
        # Report/flag review is a kg-reporting artifact; program is now
        # challenge-based (scoring handled by panitia via Google Form).
        return (
            "Review laporan tidak dipakai lagi — program sekarang berbasis "
            "challenge. Penilaian diurus panitia lewat Google Form."
        )

    @staticmethod
    async def _fetch_names_for(ids: list[str]) -> dict[str, str]:
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        return await build_volunteer_query_repository().names_for(ids)

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
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )

        rows = await build_volunteer_query_repository().list_active()
        if not rows:
            return "Belum ada volunteer aktif sebagai penerima broadcast."
        for v in rows:
            await self._notify_volunteer_dict(v, text)
        return f"📢 Broadcast terkirim ke {len(rows)} volunteer."

    # ------------------------------------------------------------------ #
    # Retired handlers — missions/assignments moved to the dashboard          #
    # ------------------------------------------------------------------ #

    async def _handle_create_mission(self, message: str) -> str:
        # Missions (kg-based) are retired — the program runs on challenges.
        return (
            "Program sekarang berbasis *challenge*, bukan misi kg. "
            "Buat & kelola challenge di dashboard → 📌 *Action Items* "
            "(jenis: Challenge)."
        )

    async def _handle_assign_volunteer(self, message: str) -> str:
        # Mission-based kg assignment is retired. Area/team are managed on the
        # dashboard now.
        return (
            "Pengaturan *area* & *tim* volunteer sekarang lewat dashboard → "
            "👥 *Volunteer* (edit kolom Area / Tim, atau bulk pindah tim). "
            "Misi kg sudah tidak dipakai."
        )

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
        from backend.agents.caption_generator import CaptionGeneratorAgent

        return await CaptionGeneratorAgent().process(message, context)

    # ------------------------------------------------------------------ #
    # Scheduled morning briefing                                          #
    # ------------------------------------------------------------------ #

    async def get_morning_briefing(self) -> str:
        from backend.agents.services.notifications import alert_fasilitator
        from backend.database.supabase_client import db
        from backend.infrastructure.composition_root import (
            build_volunteer_query_repository,
        )
        from backend.utils.action_item_resolver import ActionItemResolver

        volunteers = await build_volunteer_query_repository().list_active()
        try:
            challenges = ActionItemResolver(db).list_active_challenges()
        except Exception:
            challenges = []

        if challenges:
            ch_lines = "\n".join(
                f"  • {c.get('title')}"
                + (
                    f" (deadline {str(c['deadline'])[:10]})"
                    if c.get("deadline")
                    else ""
                )
                for c in challenges
            )
        else:
            ch_lines = "  (belum ada challenge aktif)"

        briefing = (
            "🌅 Morning briefing:\n"
            f"👥 Volunteer aktif: {len(volunteers)}\n"
            f"🎯 Challenge berjalan:\n{ch_lines}"
        )
        await alert_fasilitator(briefing)
        return briefing
