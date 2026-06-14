"""Indonesian phone number value object.

Stored canonical form: digits only, starting with country code (``62``).
Parsing handles the common writing styles encountered in the wild:

* ``+62 858-6221-2080`` → ``6285862212080``
* ``0858-6221-2080``    → ``6285862212080``
* ``6285862212080``     → ``6285862212080``
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.errors import InvalidPhone

_DIGITS = set("0123456789")
_MIN_LENGTH = 8
_MAX_LENGTH = 15


@dataclass(frozen=True)
class Phone:
    value: str

    def __post_init__(self) -> None:
        if not all(ch in _DIGITS for ch in self.value):
            raise InvalidPhone(f"non-digit in canonical form: {self.value!r}")
        if not (_MIN_LENGTH <= len(self.value) <= _MAX_LENGTH):
            raise InvalidPhone(
                f"length {len(self.value)} outside [{_MIN_LENGTH},{_MAX_LENGTH}]"
            )

    @classmethod
    def parse(cls, raw: str | None) -> "Phone":
        """Build a Phone from any user-written form."""
        if raw is None:
            raise InvalidPhone("empty phone")
        cleaned = (
            str(raw)
            .strip()
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        if not cleaned:
            raise InvalidPhone("empty phone")
        if cleaned.startswith("08"):
            cleaned = "62" + cleaned[1:]
        return cls(cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "Phone | None":
        """Like ``parse`` but returns ``None`` on failure instead of raising."""
        try:
            return cls.parse(raw)
        except InvalidPhone:
            return None

    def __str__(self) -> str:
        return self.value
