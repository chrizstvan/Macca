"""Parse prompt for the progress tracker agent (chat report extraction)."""

PARSE_PROMPT = """Extract plastic collection report data from this message.
Return ONLY valid JSON, no explanation.
Format: {"kg": float_or_null, "location": "string_or_null"}

Examples:
  "laporan 18 kg menteng" → {"kg": 18.0, "location": "Menteng"}
  "udah nih 25 kilo di cikini kak" → {"kg": 25.0, "location": "Cikini"}
  "selesai 12.5 kg gondangdia" → {"kg": 12.5, "location": "Gondangdia"}
  "laporan foto" → {"kg": null, "location": null}"""
