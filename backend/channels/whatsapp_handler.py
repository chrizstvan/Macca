"""WhatsApp Cloud API channel handler.

Parses inbound webhook payloads from Meta, dispatches them through the
agent router, sends replies back via the Graph API, and offers helper
methods for images, interactive buttons, read receipts, media download,
and fasilitator alerts.
"""

import logging
import re
from typing import Any

from backend.config import settings
from backend.database.supabase_client import db
from backend.utils.http_dispatcher import get_bytes, get_json, post_json
from backend.utils.image_handler import ImageHandler
from backend.utils.phone_utils import normalize_phone
from .base_handler import BaseChannelHandler

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v18.0"
WA_TEXT_MAX_LEN = 4096
WA_BUTTON_TITLE_MAX_LEN = 20

# Words that surface the quick-action menu. Lowercased + stripped before match.
MAIN_MENU_TRIGGERS = frozenset({
    "menu", "mulai", "home", "start", "hi", "hello", "halo", "hallo",
    "pagi", "siang", "sore", "malam",
    "/menu", "/mulai", "/start", "/home",
})
MAIN_MENU_PROMPT = "Halo! Mau ngapain hari ini?"
MAIN_MENU_BUTTONS = ("Lapor plastik", "Lihat progress", "Bantuan")


class WhatsAppHandler(BaseChannelHandler):
    """Inbound + outbound message handler for WhatsApp Cloud API."""

    def __init__(
        self,
        router: Any = None,
        image_handler: ImageHandler | None = None,
    ) -> None:
        # ``router`` is duck-typed (RouterAgent) — wired by the app on startup.
        self.router = router
        self.image_handler = image_handler or ImageHandler()

    # ------------------------------------------------------------------ #
    # Inbound                                                            #
    # ------------------------------------------------------------------ #

    async def handle_incoming(self, request_body: dict[str, Any]) -> None:
        """Parse a webhook payload, dispatch through the router, send reply."""
        ctx = await self._parse_payload(request_body)
        if not ctx:
            return

        sender_phone = ctx.get("sender_phone")
        wa_message_id = ctx.get("wa_message_id")

        # Best-effort read receipt — never block dispatch if it fails.
        if sender_phone and wa_message_id:
            try:
                await self.send_read_receipt(sender_phone, wa_message_id)
            except Exception as exc:
                logger.warning("WhatsApp read receipt failed: %s", exc)

        if self.router is None:
            logger.warning("WhatsApp router not wired — dropping message")
            return

        text = ctx.get("message") or ""
        if not text:
            return

        # Onboarding flow — runs before the router so first-contact volunteers
        # get a welcome message and unknown phones get redirected without
        # burning router/LLM cycles. Fasilitator bypasses the flow entirely.
        if sender_phone and not self.is_fasilitator(sender_phone):
            try:
                proceed_to_router = await self._handle_onboarding(
                    sender_phone=sender_phone, message=text
                )
            except Exception as exc:
                logger.exception("WhatsApp onboarding flow failed: %s", exc)
                proceed_to_router = True
            if not proceed_to_router:
                return

        # Quick-menu trigger — short-circuit before router/LLM dispatch when
        # the sender types a menu keyword. Fires for volunteers, and for
        # the fasilitator ONLY while in /test_as impersonation so the
        # impersonated volunteer view sees the buttons. Plain fasilitator
        # (no test_as) stays on the hub's free-text reply path.
        if sender_phone and text.strip().lower() in MAIN_MENU_TRIGGERS:
            from backend.agents.router_agent import test_mode_state

            in_test_mode = sender_phone in test_mode_state
            if not self.is_fasilitator(sender_phone) or in_test_mode:
                await self.send_main_menu(sender_phone)
                return

        try:
            reply = await self.router.route(text, ctx)
        except Exception as exc:
            logger.exception("WhatsApp router dispatch failed: %s", exc)
            return

        if reply and sender_phone:
            await self.send_message(sender_phone, reply)

    async def _handle_onboarding(
        self, *, sender_phone: str, message: str
    ) -> bool:
        """Run the inbound-contact use case. Returns whether to continue routing."""
        from backend.application.use_cases.handle_inbound_contact import (
            ContinueOnly,
            ReplyAndContinue,
            ReplyAndStop,
        )
        from backend.infrastructure.composition_root import (
            build_handle_inbound_contact,
        )

        outcome = await build_handle_inbound_contact().execute(
            sender_phone=sender_phone, message=message
        )

        if isinstance(outcome, ReplyAndStop):
            await self.send_message(sender_phone, outcome.text)
            return False

        if isinstance(outcome, ReplyAndContinue):
            for pre in outcome.pre_messages:
                await self.send_message(sender_phone, pre)
            return True

        # ContinueOnly
        assert isinstance(outcome, ContinueOnly)
        return True

    async def _parse_payload(
        self, request_body: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Normalise a Meta webhook payload into a single-message context dict.

        Returns ``None`` for status-only events (delivered/read/sent) so the
        caller can short-circuit without dispatching anything.
        """
        try:
            change = request_body["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError, TypeError):
            logger.warning("WhatsApp payload missing entry/changes: %r", request_body)
            return None

        messages = change.get("messages") or []
        if not messages:
            return None

        message = messages[0]
        sender_phone = message.get("from", "")
        message_type = message.get("type")
        text = ""
        photo_url: str | None = None

        if message_type == "text":
            text = (message.get("text") or {}).get("body", "")
        elif message_type == "image":
            image = message.get("image") or {}
            media_id = image.get("id")
            text = image.get("caption") or "laporan foto"
            if media_id and settings.whatsapp_access_token:
                volunteer_name = await self._lookup_volunteer_name_by_phone(
                    sender_phone
                )
                photo_url = await self.image_handler.upload_from_whatsapp(
                    media_id,
                    settings.whatsapp_access_token,
                    sender_phone,
                    volunteer_name=volunteer_name,
                )
        elif message_type == "interactive":
            interactive = message.get("interactive") or {}
            reply = (interactive.get("button_reply") or interactive.get("list_reply") or {})
            text = reply.get("title") or reply.get("id") or ""
        else:
            text = f"[{message_type} message — belum didukung]"

        ctx: dict[str, Any] = {
            "channel": "whatsapp",
            "sender_phone": sender_phone,
            "wa_message_id": message.get("id"),
            "message": text,
            "photo_url": photo_url,
            "chat_type": "private",
        }
        # If the fasilitator forwards a photo report, mark the source so the
        # progress tracker skips photo verification and auto-verifies. Skip
        # the tag while the fasilitator is in /test_as impersonation — in
        # that mode they are acting as the volunteer, so the photo MUST go
        # through the verifier like any other volunteer upload.
        if message_type == "image" and self.is_fasilitator(sender_phone):
            from backend.agents.router_agent import test_mode_state

            if sender_phone not in test_mode_state:
                ctx["source"] = "fasilitator_relay"
        return ctx

    # ------------------------------------------------------------------ #
    # Outbound — text / image / buttons                                   #
    # ------------------------------------------------------------------ #

    async def send_message(self, to: str, text: str) -> bool:
        """POST a text message to the WhatsApp Cloud API."""
        if not self._creds_ready():
            return False
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": self._to_whatsapp_markdown(text)[:WA_TEXT_MAX_LEN]},
        }
        return await self._post_messages(payload)

    async def send_image(
        self, to: str, image_url: str, caption: str = ""
    ) -> bool:
        """POST an image message (by URL) to the WhatsApp Cloud API."""
        if not self._creds_ready():
            return False
        image: dict[str, Any] = {"link": image_url}
        if caption:
            image["caption"] = self._to_whatsapp_markdown(caption)
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": image,
        }
        return await self._post_messages(payload)

    async def send_buttons(
        self, to: str, body_text: str, buttons: list[str]
    ) -> bool:
        """Send an interactive reply-button message (max 3 buttons)."""
        if not self._creds_ready():
            return False
        if not buttons:
            return await self.send_message(to, body_text)
        if len(buttons) > 3:
            logger.warning("WhatsApp allows max 3 buttons; truncating from %d", len(buttons))
        button_objects = [
            {
                "type": "reply",
                "reply": {
                    "id": f"btn_{idx}",
                    "title": label[:WA_BUTTON_TITLE_MAX_LEN],
                },
            }
            for idx, label in enumerate(buttons[:3])
        ]
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": self._to_whatsapp_markdown(body_text)[:1024]},
                "action": {"buttons": button_objects},
            },
        }
        return await self._post_messages(payload)

    async def send_main_menu(self, to: str) -> bool:
        """Send the quick-action reply-button menu (Lapor / Progress / Bantuan)."""
        return await self.send_buttons(
            to,
            MAIN_MENU_PROMPT,
            list(MAIN_MENU_BUTTONS),
        )

    async def send_list(
        self,
        to: str,
        body_text: str,
        button_text: str,
        rows: list[dict],
        section_title: str = "Pilihan",
        header_text: str | None = None,
    ) -> bool:
        """Send an interactive list message (up to 10 rows per section).

        ``rows`` is a list of dicts with keys ``id``, ``title`` (≤24 chars),
        and optional ``description`` (≤72 chars). WA renders each row as a
        tappable option; the tap returns ``interactive.list_reply`` whose
        ``title`` flows back through ``_parse_payload`` as the message text.
        """
        if not self._creds_ready():
            return False
        if not rows:
            return await self.send_message(to, body_text)
        rendered_rows = [
            {
                "id": str(row.get("id") or f"row_{idx}")[:200],
                "title": str(row.get("title") or "")[:24],
                "description": str(row.get("description") or "")[:72],
            }
            for idx, row in enumerate(rows[:10])
        ]
        action: dict[str, Any] = {
            "button": button_text[:20],
            "sections": [
                {"title": section_title[:24], "rows": rendered_rows}
            ],
        }
        interactive: dict[str, Any] = {
            "type": "list",
            "body": {"text": self._to_whatsapp_markdown(body_text)[:1024]},
            "action": action,
        }
        if header_text:
            interactive["header"] = {
                "type": "text",
                "text": header_text[:60],
            }
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        return await self._post_messages(payload)

    async def send_quiz(self, to: str, quiz: dict) -> bool:
        """Render a ``QuizSpec``-shaped dict as an interactive list message.

        Each option (e.g. ``"A) Kode 3 (PVC)"``) is split into a single-letter
        ``title`` (so the inbound list-reply re-enters the router quiz step
        with just ``"A"``) plus the rest of the option text as
        ``description``.
        """
        question = quiz.get("question") or ""
        options = quiz.get("options") or []
        rows = []
        for raw in options[:10]:
            text = str(raw).strip()
            # Split at the first ")" so "A) Kode 3 (PVC)" → ("A", "Kode 3 (PVC)").
            if ")" in text:
                letter, _, rest = text.partition(")")
                letter = letter.strip()
                description = rest.strip()
            else:
                letter = text[:1]
                description = text[1:].strip()
            if not letter:
                continue
            rows.append(
                {
                    "id": f"quiz_{letter}",
                    "title": letter,
                    "description": description,
                }
            )
        body = f"🧠 *Quiz Plastik Minggu Ini!*\n\n{question}"
        return await self.send_list(
            to,
            body_text=body,
            button_text="Pilih jawaban",
            rows=rows,
            section_title="Pilihan A–D",
        )

    # ------------------------------------------------------------------ #
    # Read receipts                                                       #
    # ------------------------------------------------------------------ #

    async def send_read_receipt(self, to: str, message_id: str) -> None:
        """Mark an inbound WhatsApp message as read.

        ``to`` is included to satisfy the BaseChannelHandler signature but is
        not used by the Graph API — ``message_id`` alone identifies the chat.
        """
        if not self._creds_ready() or not message_id:
            return
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        await self._post_messages(payload)

    # ------------------------------------------------------------------ #
    # Media download (raw bytes)                                          #
    # ------------------------------------------------------------------ #

    async def download_media(self, media_id: str) -> bytes | None:
        """Resolve a Graph media_id to a signed URL and return the bytes."""
        if not settings.whatsapp_access_token or not media_id:
            return None
        ok, meta = await get_json(
            f"{GRAPH_BASE}/{media_id}",
            auth_token=settings.whatsapp_access_token,
            timeout=30,
            log_label="whatsapp.media_meta",
        )
        if not ok or not meta:
            return None
        media_url = meta.get("url")
        if not media_url:
            logger.error("WhatsApp media %s: missing 'url' in metadata", media_id)
            return None
        return await get_bytes(
            media_url,
            auth_token=settings.whatsapp_access_token,
            timeout=30,
            log_label="whatsapp.media_bytes",
        )

    # ------------------------------------------------------------------ #
    # Fasilitator alert                                                   #
    # ------------------------------------------------------------------ #

    async def send_alert(self, text: str) -> None:
        """DM the fasilitator at ``settings.fasilitator_phone``."""
        phone = normalize_phone(settings.fasilitator_phone)
        if not phone:
            logger.warning("WhatsApp send_alert: fasilitator_phone not configured")
            return
        await self.send_message(phone, f"🚨 ALERT: {text}")

    # ------------------------------------------------------------------ #
    # Identity                                                            #
    # ------------------------------------------------------------------ #

    def is_fasilitator(self, sender_id: str) -> bool:
        """True if ``sender_id`` (phone) matches the configured fasilitator."""
        sender = normalize_phone(sender_id)
        fasilitator = normalize_phone(settings.fasilitator_phone)
        return bool(sender and fasilitator and sender == fasilitator)

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _creds_ready(self) -> bool:
        if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
            logger.error("WhatsApp credentials missing — cannot call Graph API")
            return False
        return True

    async def _post_messages(self, payload: dict[str, Any]) -> bool:
        url = f"{GRAPH_BASE}/{settings.whatsapp_phone_number_id}/messages"
        ok, _body = await post_json(
            url,
            payload,
            auth_token=settings.whatsapp_access_token,
            log_label="whatsapp.send",
        )
        return ok

    @staticmethod
    def _to_whatsapp_markdown(text: str) -> str:
        """Rewrite common Markdown/HTML formatting into WhatsApp's syntax.

        Telegram-flavoured HTML (``<b>``, ``<i>``, ``<code>``) and CommonMark
        (``**bold**``, ``__italic__``) are normalised to WhatsApp's wire
        format: ``*bold*``, ``_italic_``, ``~strike~``, `` `code` ``.
        Any other tags are stripped so they don't show up as literal text.
        """
        if not text:
            return ""
        converted = text
        # HTML → WA
        converted = re.sub(r"<\s*(b|strong)\s*>(.*?)<\s*/\s*\1\s*>", r"*\2*", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*(i|em)\s*>(.*?)<\s*/\s*\1\s*>", r"_\2_", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*(s|strike|del)\s*>(.*?)<\s*/\s*\1\s*>", r"~\2~", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*code\s*>(.*?)<\s*/\s*code\s*>", r"`\1`", converted, flags=re.IGNORECASE | re.DOTALL)
        converted = re.sub(r"<\s*br\s*/?\s*>", "\n", converted, flags=re.IGNORECASE)
        # Drop any remaining HTML tags
        converted = re.sub(r"<[^>]+>", "", converted)
        # CommonMark → WA: **bold** → *bold*, __italic__ → _italic_
        converted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", converted, flags=re.DOTALL)
        converted = re.sub(r"__(.+?)__", r"_\1_", converted, flags=re.DOTALL)
        return converted

    # ``_normalize_phone`` kept as an alias so subclasses / external callers
    # that reference ``WhatsAppHandler._normalize_phone`` keep working; the
    # canonical implementation lives in ``backend.utils.phone_utils``.
    _normalize_phone = staticmethod(normalize_phone)

    @staticmethod
    async def _lookup_volunteer_name_by_phone(phone: str) -> str | None:
        """Quick lookup so uploaded photos get a human-readable filename."""
        if not phone:
            return None
        try:
            rows = (
                db.table("volunteers")
                .select("name")
                .eq("phone", normalize_phone(phone))
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            logger.warning("volunteer name lookup failed for %s: %s", phone, exc)
            return None
        return (rows[0].get("name") if rows else None) or None
