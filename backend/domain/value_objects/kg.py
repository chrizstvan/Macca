"""Reported plastic weight, with business invariant enforcement."""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.errors import InvalidKg

MIN_KG = 0.0
MAX_KG = 999.0


@dataclass(frozen=True)
class Kg:
    """A weight in kilograms, strictly positive and ≤ 999.

    Enforced at construction so downstream code can rely on validity
    without re-checking. Use ``Kg.try_parse`` if you need a non-raising
    builder (e.g. when normalising user input).
    """

    value: float

    def __post_init__(self) -> None:
        if self.value <= MIN_KG:
            raise InvalidKg("Berat harus lebih dari 0 kg")
        if self.value > MAX_KG:
            raise InvalidKg("Berat terlalu besar, mohon periksa kembali")

    @classmethod
    def try_parse(cls, raw: float | int | str | None) -> "Kg | None":
        if raw is None:
            return None
        try:
            return cls(float(raw))
        except (InvalidKg, TypeError, ValueError):
            return None

    def diff(self, other: "Kg") -> float:
        return abs(self.value - other.value)

    def __float__(self) -> float:
        return self.value
