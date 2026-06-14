"""Who is talking to the bot, from the agent's perspective."""

from __future__ import annotations

from enum import Enum


class Persona(str, Enum):
    """The two routing identities.

    ``str`` mix-in keeps these JSON/dict friendly without losing
    iteration safety on the enum membership.
    """

    FASILITATOR = "fasilitator"
    VOLUNTEER = "volunteer"


class Channel(str, Enum):
    """Inbound channel a message arrived on."""

    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    GOOGLE_FORM = "google_form"
