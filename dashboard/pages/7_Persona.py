"""Persona configurator — controls how the volunteer-facing agent speaks.

All settings persist into ``fasilitator_context`` (key/value rows). The
backend's volunteer-facing agents are expected to read these keys at
runtime and inject them into their system prompts; see the note at the
bottom of this file for the wiring guidance.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from utils import theme  # noqa: E402,F401 (auto-installs Plotly defaults)
from utils.api import preview_persona_response  # noqa: E402
from utils.db import clear_caches, supabase  # noqa: E402

st.set_page_config(page_title="Persona — Macca", page_icon="🎭", layout="wide")
st.title("🎭 Konfigurasi Persona Agent")
st.caption("Atur bagaimana agent berbicara kepada volunteer.")


# --------------------------------------------------------------------------- #
# Existing context                                                             #
# --------------------------------------------------------------------------- #


persona_rows = supabase.table("fasilitator_context").select("*").execute().data or []
current = {d["key"]: d.get("value", "") for d in persona_rows}

TONE_OPTIONS = (
    "Sangat kasual", "Kasual", "Netral", "Formal", "Sangat formal",
)
ADDRESS_LABELS = (
    "Nama saja (Rizki)",
    "Kak + nama (Kak Rizki)",
    "Kamu",
    "Anda",
)
ADDRESS_KEYS = ("name", "kak_name", "kamu", "anda")
LABEL_BY_KEY = dict(zip(ADDRESS_KEYS, ADDRESS_LABELS))
KEY_BY_LABEL = dict(zip(ADDRESS_LABELS, ADDRESS_KEYS))


# --------------------------------------------------------------------------- #
# Editor (no st.form — preview needs live values; Save via plain button)      #
# --------------------------------------------------------------------------- #


st.subheader("Identitas Agent")
agent_name = st.text_input(
    "Nama Agent",
    value=current.get("agent_name", "Asisten GBP"),
    help="Nama yang digunakan agent saat menyapa volunteer.",
)
agent_role = st.text_input(
    "Peran Agent",
    value=current.get(
        "agent_role", "asisten program Generasi Bebas Plastik"
    ),
    help="Deskripsi singkat peran agent.",
)

st.subheader("Gaya Bahasa")
tone = st.select_slider(
    "Tingkat keformalan",
    options=TONE_OPTIONS,
    value=current.get("tone") if current.get("tone") in TONE_OPTIONS else "Kasual",
)
use_emoji = st.toggle(
    "Gunakan emoji dalam respons",
    value=(current.get("use_emoji", "true") == "true"),
)
address_default = LABEL_BY_KEY.get(
    current.get("address_style", "kamu"), "Kamu"
)
address_style_label = st.radio(
    "Cara menyapa volunteer",
    ADDRESS_LABELS,
    index=ADDRESS_LABELS.index(address_default),
    horizontal=True,
)

st.subheader("Pesan Sambutan")
greeting_template = st.text_area(
    "Template pesan pertama kali",
    value=current.get(
        "greeting_template",
        "Halo {nama}! Selamat datang di program Generasi Bebas Plastik 🌱",
    ),
    help="Gunakan ``{nama}`` untuk nama volunteer, ``{area}`` untuk area tugas.",
)

st.subheader("Batasan Respons")
try:
    max_default = int(current.get("max_sentences", "4"))
except (TypeError, ValueError):
    max_default = 4
max_response_sentences = st.slider(
    "Maksimal kalimat per respons",
    min_value=2,
    max_value=8,
    value=max_default,
    help="Mengontrol panjang respons + penggunaan token.",
)
personality_notes = st.text_area(
    "Catatan kepribadian tambahan",
    value=current.get("personality_notes", ""),
    placeholder="Contoh: Selalu awali dengan empati. Hindari kata 'harus'.",
)


# --------------------------------------------------------------------------- #
# Save                                                                         #
# --------------------------------------------------------------------------- #


if st.button("💾 Simpan Persona", type="primary"):
    payload = {
        "agent_name": agent_name.strip(),
        "agent_role": agent_role.strip(),
        "tone": tone,
        "use_emoji": str(bool(use_emoji)).lower(),
        "address_style": KEY_BY_LABEL[address_style_label],
        "greeting_template": greeting_template.strip(),
        "max_sentences": str(int(max_response_sentences)),
        "personality_notes": personality_notes.strip(),
    }
    failed: list[str] = []
    for key, value in payload.items():
        try:
            supabase.table("fasilitator_context").upsert(
                {"key": key, "value": value}, on_conflict="key"
            ).execute()
        except Exception as exc:
            failed.append(f"{key}: {exc}")
    clear_caches()
    if failed:
        st.error("Sebagian gagal disimpan:\n" + "\n".join(failed))
    else:
        st.success("✅ Persona agent berhasil diperbarui!")
        st.rerun()


# --------------------------------------------------------------------------- #
# Preview                                                                      #
# --------------------------------------------------------------------------- #


st.divider()
st.subheader("🔍 Preview")
preview_name = st.text_input("Preview dengan nama:", value="Rizki")

if st.button("Jalankan preview"):
    with st.spinner("Menggenerate sample respons…"):
        try:
            preview = preview_persona_response(
                test_name=preview_name,
                settings={
                    "agent_name": agent_name,
                    "agent_role": agent_role,
                    "tone": tone,
                    "use_emoji": bool(use_emoji),
                    "address_style": KEY_BY_LABEL[address_style_label],
                    "greeting_template": greeting_template,
                    "max_sentences": int(max_response_sentences),
                    "personality_notes": personality_notes,
                },
            )
            with st.expander("📝 Greeting (template diisi)", expanded=True):
                st.write(preview.get("greeting", ""))
            with st.expander("💬 Sample respons agent", expanded=True):
                st.write(preview.get("response", ""))
        except Exception as exc:
            st.error(f"Gagal preview: {exc}")


# --------------------------------------------------------------------------- #
# Wiring note for backend devs                                                 #
# --------------------------------------------------------------------------- #


st.divider()
st.caption(
    "ℹ️ Agar persona ini benar-benar dipakai oleh agent volunteer-facing, "
    "tambahkan helper di backend yang membaca semua key dari "
    "``fasilitator_context`` dan menyuntikkannya ke SYSTEM_PROMPT setiap "
    "agent (mission_briefing, progress_tracker, volunteer_support). "
    "Contoh: ``persona = get_fasilitator_context(); SYSTEM_PROMPT += "
    "format_persona(persona)``."
)
