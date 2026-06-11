"""Converts collected plastic weight into tangible environmental impact figures."""

BOTTLES_PER_KG = 71  # avg 14 g per 600 ml bottle → ~71 bottles per kg
CO2_KG_PER_KG = 3.0  # 1 kg plastic recycled prevents ~3 kg CO2
WATER_LITERS_PER_KG = 2.0  # producing 1 kg virgin plastic uses ~2 L water


class ImpactCalculator:
    """Static conversions from kg of plastic to bottles, CO2, and water figures."""

    @staticmethod
    def kg_to_bottles(kg: float) -> int:
        return round(kg * BOTTLES_PER_KG)

    @staticmethod
    def kg_to_co2_prevented(kg: float) -> float:
        return round(kg * CO2_KG_PER_KG, 2)

    @staticmethod
    def kg_to_liters_water_saved(kg: float) -> float:
        return round(kg * WATER_LITERS_PER_KG, 2)

    @staticmethod
    def format_impact_summary(kg: float) -> dict:
        return {
            "kg": kg,
            "bottles": ImpactCalculator.kg_to_bottles(kg),
            "co2_kg": ImpactCalculator.kg_to_co2_prevented(kg),
            "water_liters": ImpactCalculator.kg_to_liters_water_saved(kg),
        }

    @staticmethod
    def format_impact_narrative(kg: float, lang: str = "id") -> str:
        bottles = _fmt(ImpactCalculator.kg_to_bottles(kg), lang)
        co2 = _fmt(ImpactCalculator.kg_to_co2_prevented(kg), lang)
        water = _fmt(ImpactCalculator.kg_to_liters_water_saved(kg), lang)
        if lang == "en":
            return (
                f"Equivalent to saving {bottles} plastic bottles, preventing "
                f"{co2} kg of CO₂ emissions, and saving {water} liters of water"
            )
        return (
            f"Setara menyelamatkan {bottles} botol plastik, mencegah "
            f"{co2} kg emisi CO₂, dan menghemat {water} liter air"
        )


def _fmt(value: float, lang: str = "id") -> str:
    """Format a number with locale separators ('7.100' / '12,5' for id)."""
    if value == int(value):
        text = f"{int(value):,}"
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    if lang == "en":
        return text
    return text.translate(str.maketrans(",.", ".,"))


if __name__ == "__main__":
    calc = ImpactCalculator

    assert calc.kg_to_bottles(1) == 71
    assert calc.kg_to_bottles(100) == 7100
    assert calc.kg_to_bottles(0) == 0
    assert calc.kg_to_bottles(0.5) == 36  # rounds 35.5 → 36

    assert calc.kg_to_co2_prevented(1) == 3.0
    assert calc.kg_to_co2_prevented(100) == 300.0
    assert calc.kg_to_co2_prevented(2.5) == 7.5

    assert calc.kg_to_liters_water_saved(1) == 2.0
    assert calc.kg_to_liters_water_saved(100) == 200.0
    assert calc.kg_to_liters_water_saved(0.25) == 0.5

    summary = calc.format_impact_summary(100)
    assert summary == {"kg": 100, "bottles": 7100, "co2_kg": 300.0, "water_liters": 200.0}

    narrative = calc.format_impact_narrative(100)
    assert narrative == (
        "Setara menyelamatkan 7.100 botol plastik, mencegah "
        "300 kg emisi CO₂, dan menghemat 200 liter air"
    ), narrative

    narrative_en = calc.format_impact_narrative(100, lang="en")
    assert "7,100 plastic bottles" in narrative_en, narrative_en

    assert _fmt(12.5) == "12,5"
    assert _fmt(1234567) == "1.234.567"
    assert _fmt(12.5, "en") == "12.5"

    print("✅ all ImpactCalculator tests passed")
