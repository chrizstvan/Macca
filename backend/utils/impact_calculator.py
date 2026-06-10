"""Pure-function impact score calculator used by ImpactAnalyzerAgent."""

from typing import Any


# Weights used to compute a 0–100 composite impact score
_WEIGHTS: dict[str, float] = {
    "people_helped": 0.40,
    "volunteer_hours": 0.25,
    "completion_pct": 0.20,
    "resources_distributed_count": 0.15,
}

_MAX_VALUES: dict[str, float] = {
    "people_helped": 500,
    "volunteer_hours": 200,
    "completion_pct": 100,
    "resources_distributed_count": 100,
}


def calculate_impact_score(metrics: dict[str, Any]) -> float:
    """Compute a weighted impact score in the range [0, 100].

    Accepts a flat metrics dict with any subset of the known keys.
    Unknown keys are ignored; missing keys default to 0.
    """
    if not metrics:
        return 0.0

    # Normalise resources_distributed: accept count or a nested dict
    resources = metrics.get("resources_distributed", {})
    resources_count = (
        len(resources) if isinstance(resources, dict) else int(resources)
    )

    normalised = {
        "people_helped": float(metrics.get("people_helped", 0)),
        "volunteer_hours": float(metrics.get("volunteer_hours", 0)),
        "completion_pct": float(metrics.get("completion_pct", 0)),
        "resources_distributed_count": float(resources_count),
    }

    score = 0.0
    for key, weight in _WEIGHTS.items():
        max_val = _MAX_VALUES[key]
        capped = min(normalised[key], max_val)
        score += (capped / max_val) * weight * 100

    return round(score, 2)


def format_impact_summary(metrics: dict[str, Any]) -> str:
    """Return a one-line human-readable summary of key impact metrics."""
    people = metrics.get("people_helped", 0)
    hours = metrics.get("volunteer_hours", 0)
    score = calculate_impact_score(metrics)
    return f"{people} people helped · {hours:.1f} volunteer hours · impact score {score}/100"
