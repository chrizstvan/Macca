"""Caption Generator agent — social-media caption for challenge posts.

Two sources, one output (a ready-to-post Instagram caption, 2-3 sentences,
containing an environmental impact / encouragement line):

1. **From text** — the volunteer describes what they did
   ("buatkan caption, tadi aku bawa tumbler ke kampus").
2. **From photo** — the volunteer sends a photo (Claude vision reads it).
   Repurposes the now-disabled report-photo pipeline: the channel already
   uploads the image and puts its URL in ``context['photo_url']``.

Either way the active challenge's mandatory hashtags/tags (from
``action_items`` type=challenge) are injected so captions stay compliant.
"""

from __future__ import annotations

import base64
import logging

import httpx

from .base_agent import BaseAgent, COMPLEX_MODEL
from .intent_registry import register_intent
from .services.challenge_context import build_active_challenge_block

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Kamu asisten pembuat caption media sosial untuk relawan program Generasi "
    "Bebas Plastik. Tugasmu: buat SATU caption Instagram siap posting.\n"
    "Aturan:\n"
    "- MAKSIMAL 3 kalimat. Jangan lebih dari 3 kalimat. Singkat dan padat.\n"
    "- Bahasa Indonesia santai dan hangat.\n"
    "- WAJIB sisipkan dampak positif lingkungan atau ajakan/encouragement "
    "menjaga lingkungan.\n"
    "- JANGAN pakai tanda em dash (—) atau en dash (–). Pakai koma atau titik "
    "biasa saja.\n"
    "- Kalau ada info CHALLENGE AKTIF di bawah, gunakan hashtag & tag wajibnya "
    "PERSIS seperti tertulis. Jangan mengarang hashtag/tag yang tidak ada.\n"
    "- Kalau tidak ada challenge aktif, pakai hashtag umum #GenerasiBebasPlastik.\n"
    "- Letakkan hashtag & tag di baris terpisah paling bawah.\n"
    "Keluarkan HANYA caption-nya, siap copy-paste. Tanpa penjelasan tambahan."
)


@register_intent(
    name="make_caption",
    description=(
        "minta dibuatkan caption / konten / tulisan / post untuk media sosial "
        "(Instagram/story/reels/tiktok/WA) tentang aksi challenge — dari "
        "deskripsi teks ATAU dari foto yang dikirim"
    ),
    examples=(
        "buatkan caption dong",
        "bikinin caption buat postingan ig",
        "tolong buatkan caption instagram",
        "tolong buat caption untuk foto ini",
        "caption buat story challenge",
        "caption tiktok untuk reels hari ini",
        "bikin post story wa tentang aksi hari ini",
        "minta caption reels aksi 3r",
        "buatkan caption, tadi aku bawa tumbler ke kampus",
    ),
)
class CaptionGeneratorAgent(BaseAgent):
    """Generate a ready-to-post caption from a text description or a photo."""

    def __init__(self) -> None:
        super().__init__(
            name="caption_generator",
            description="Membuat caption media sosial dari teks atau foto",
        )

    async def process(self, message: str, context: dict) -> str:
        context = self.build_context_flags(context)
        telegram_id = context.get("telegram_id")

        challenge_block = build_active_challenge_block()
        system_prompt = (
            f"{_SYSTEM_PROMPT}\n\n{challenge_block}"
            if challenge_block
            else _SYSTEM_PROMPT
        )

        photo_url = context.get("photo_url")
        if photo_url:
            reply = await self._caption_from_photo(photo_url, message, system_prompt)
        else:
            reply = await self._caption_from_text(message, system_prompt)

        reply = f"📝 Caption siap posting:\n\n{self._sanitize(reply)}"
        if telegram_id:
            await self.save_chat_history(telegram_id, "user", message, self.name)
            await self.save_chat_history(telegram_id, "assistant", reply, self.name)
        return reply

    @staticmethod
    def _sanitize(text: str) -> str:
        """Strip em/en dashes the model may still emit despite the prompt."""
        cleaned = (text or "").strip()
        cleaned = cleaned.replace(" — ", ", ").replace(" – ", ", ")
        cleaned = cleaned.replace("—", ",").replace("–", ",")
        return cleaned

    # ------------------------------------------------------------------ #
    # Text path                                                          #
    # ------------------------------------------------------------------ #

    async def _caption_from_text(self, message: str, system_prompt: str) -> str:
        prompt = (
            "Buat caption berdasarkan deskripsi aksi relawan berikut:\n"
            f'"{message.strip()}"'
        )
        return await self.call_claude(
            system_prompt,
            [{"role": "user", "content": prompt}],
            model=COMPLEX_MODEL,
            max_tokens=250,
        )

    # ------------------------------------------------------------------ #
    # Photo (vision) path                                                #
    # ------------------------------------------------------------------ #

    async def _caption_from_photo(
        self, photo_url: str, message: str, system_prompt: str
    ) -> str:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(photo_url)
                resp.raise_for_status()
                image_bytes = resp.content
                media_type = (
                    resp.headers.get("content-type", "image/jpeg").split(";")[0]
                )
        except httpx.HTTPError as exc:
            logger.warning("caption photo fetch failed (%s) — fallback to text", exc)
            return await self._caption_from_text(message, system_prompt)

        image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        instruction = (
            "Lihat foto ini dan buat caption sesuai aturan. Konteks tambahan "
            f"dari relawan: \"{message.strip()}\"."
            if message.strip()
            else "Lihat foto ini dan buat caption sesuai aturan."
        )
        try:
            response = await self.anthropic_client.messages.create(
                model=COMPLEX_MODEL,
                max_tokens=250,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": instruction},
                        ],
                    }
                ],
            )
            return response.content[0].text
        except Exception as exc:  # noqa: BLE001 — vision failure → text fallback
            logger.warning("caption vision call failed (%s) — fallback to text", exc)
            return await self._caption_from_text(message, system_prompt)
