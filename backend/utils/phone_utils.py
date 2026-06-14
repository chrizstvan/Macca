"""Phone-number helpers shared across agents and channel handlers."""

from __future__ import annotations


def normalize_phone(phone: str | None) -> str:
    """Normalize to digits-only Indonesian E.164 (``62xxxxxxxxx``).

    Strips ``+``, spaces, hyphens, and parentheses; rewrites a leading
    ``08`` to ``628``. Returns an empty string for empty/None input.
    """
    if not phone:
        return ""
    cleaned = (
        str(phone).strip()
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    if cleaned.startswith("08"):
        cleaned = "62" + cleaned[1:]
    return cleaned
