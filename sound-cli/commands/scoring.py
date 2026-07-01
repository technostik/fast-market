from __future__ import annotations


def target_band_score(value: float, low: float, ideal_low: float, ideal_high: float, high: float) -> float:
    """100 inside [ideal_low, ideal_high], 0 at/beyond low or high, linear in between."""
    if value <= low or value >= high:
        return 0.0
    if ideal_low <= value <= ideal_high:
        return 100.0
    if value < ideal_low:
        return 100.0 * (value - low) / max(1e-9, ideal_low - low)
    return 100.0 * (high - value) / max(1e-9, high - ideal_high)


def inverse_band_score(value: float, good_max: float, bad_min: float) -> float:
    """For 'lower is better' metrics (e.g. jitter/shimmer perturbation): 100 at/below
    good_max, 0 at/above bad_min, linear in between."""
    if value <= good_max:
        return 100.0
    if value >= bad_min:
        return 0.0
    return 100.0 * (bad_min - value) / max(1e-9, bad_min - good_max)
