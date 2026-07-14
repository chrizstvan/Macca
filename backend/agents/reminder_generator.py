"""Reminder-draft generator agent.

Given an ``action_items`` row and a fasilitator persona, asks Claude Sonnet
for a short, on-persona WhatsApp reminder. All content is pulled straight
from the action item — no manual input — and the per-type instruction tailors
the ask (challenge vs submission vs pre-test …).

Presentation-layer helper: it only turns data + persona into text. It does
not persist or send anything; the reminder flow takes the returned draft,
gets fasilitator approval, then schedules it (see
``backend.utils.schedule_parser`` + the ``scheduled_messages`` dispatch job).
"""

from __future__ import annotations

import logging

from .base_agent import BaseAgent, COMPLEX_MODEL

logger = logging.getLogger(__name__)

# Per-type guidance steering what the reminder should emphasise.
TYPE_INSTRUCTIONS: dict[str, str] = {
    "challenge": (
        "Ajak volunteer mengerjakan challenge. Sebutkan target, deadline, "
        "dan hadiah kalau ada. Beri semangat."
    ),
    "submission": (
        "Ingatkan volunteer submit laporan. Sertakan LINK dan deadline. "
        "Jelaskan singkat apa yang perlu di-submit."
    ),
    "kelas": (
        "Ingatkan jadwal kelas. Sebutkan judul, waktu, dan lokasi/link. "
        "Ajak hadir tepat waktu."
    ),
    "presensi": (
        "Ingatkan isi presensi. Sertakan link presensi dan batas waktu."
    ),
    "pre_test": (
        "Ingatkan isi pre-test SEBELUM kegiatan. Sertakan link dan deadline. "
        "Tekankan pentingnya untuk mengukur pemahaman awal."
    ),
    "post_test": (
        "Ingatkan isi post-test SETELAH kegiatan. Sertakan link dan deadline. "
        "Tekankan untuk melihat perkembangan pemahaman."
    ),
    "tautan": (
        "Ingatkan isi/buka tautan penting. Sertakan link dan jelaskan "
        "kenapa penting."
    ),
    "buku_saku": (
        "Ajak volunteer baca buku saku. Sertakan link/lokasi. Jelaskan "
        "manfaatnya untuk memahami program lebih baik."
    ),
}
_FALLBACK_INSTRUCTION = "Buat reminder yang sesuai."


class ReminderGenerator(BaseAgent):
    """Action item + persona → on-persona WhatsApp reminder draft."""

    def __init__(self) -> None:
        super().__init__(
            name="reminder_generator",
            description="Generates on-persona reminder drafts from action items.",
        )

    async def process(self, message: str, context: dict) -> str:
        """BaseAgent entry point — delegate to :meth:`generate_draft`.

        Expects ``context["action_item"]`` and ``context["persona"]``; the
        free-form ``message`` is unused (all content comes from the action
        item).
        """
        return await self.generate_draft(
            context.get("action_item") or {},
            context.get("persona") or {},
        )

    async def generate_draft(self, action_item: dict, persona: dict) -> str:
        """Generate a reminder draft from an ``action_items`` row.

        Uses Claude Sonnet for natural, on-persona messaging. Pulls every
        field from ``action_item`` directly; missing fields render as ``-``
        and the prompt instructs the model not to mention them.
        """
        instruction = TYPE_INSTRUCTIONS.get(
            action_item.get("type"), _FALLBACK_INSTRUCTION
        )

        system_prompt = (
            f'Kamu adalah {persona.get("agent_name", "Asisten GBP")}.\n'
            f'Tone: {persona.get("tone", "Kasual")}. '
            f'Emoji: {persona.get("use_emoji", True)}.\n\n'
            "Buat pesan reminder WhatsApp yang singkat (maks 5-6 baris), "
            "hangat, dan jelas.\n"
            f"{instruction}\n\n"
            "=== DATA ===\n"
            f'Judul: {action_item.get("title", "-")}\n'
            f'Deskripsi: {action_item.get("description", "-")}\n'
            f'Link: {action_item.get("link_url", "-")}\n'
            f'Deadline: {action_item.get("deadline", "-")}\n'
            f'Waktu/Jadwal: {action_item.get("scheduled_at", "-")}\n'
            f'Lokasi: {action_item.get("location", "-")}\n'
            f'Hadiah: {action_item.get("reward", "-")}\n\n'
            "Gunakan {nama} sebagai placeholder nama volunteer (akan diganti "
            "saat kirim).\n"
            'Jangan karang data yang tidak ada. Kalau field "-", jangan '
            "sebutkan."
        )

        return await self.call_claude(
            system_prompt,
            [{"role": "user", "content": "Buat draft reminder."}],
            model=COMPLEX_MODEL,
        )

    async def generate_combined_draft(
        self, action_items: list[dict], persona: dict
    ) -> str:
        """Combine 2+ action items into one coherent reminder message.

        Common combos: kelas + pre_test, presensi + post_test,
        challenge + submission. Orders the asks logically and folds every
        relevant link/deadline into a single WhatsApp message.
        """
        items_summary = "\n".join(
            f"- [{a.get('type', '-')}] {a.get('title', '-')}: "
            f"link={a.get('link_url', '-')}, "
            f"deadline={a.get('deadline', '-')}, "
            f"jadwal={a.get('scheduled_at', '-')}"
            for a in action_items
        )

        system_prompt = (
            "Buat SATU pesan reminder WhatsApp yang menggabungkan beberapa hal "
            "berikut secara rapi dan natural (jangan terkesan ditempel). "
            "Urutkan logis (misal: hadir kelas dulu, lalu isi pre-test). "
            "Sertakan semua link & deadline yang relevan. Maks 8 baris.\n\n"
            f'Persona: {persona.get("agent_name", "Asisten GBP")}\n\n'
            "=== HAL YANG DIGABUNG ===\n" + items_summary + "\n\n"
            "Pakai {nama} sebagai placeholder. Jangan karang data yang tidak ada."
        )

        return await self.call_claude(
            system_prompt,
            [{"role": "user", "content": "Buat reminder gabungan."}],
            model=COMPLEX_MODEL,
        )
