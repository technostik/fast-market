from __future__ import annotations


def target_band_score(value: float, low: float, ideal_low: float, ideal_high: float, high: float) -> float:
    """100 inside [ideal_low, ideal_high], 0 at/beyond low or high, linear in between.
    Use for genuinely "mid-range is best" metrics (e.g. spectral centroid resonance:
    too low reads dull, too high reads thin/harsh)."""
    if value <= low or value >= high:
        return 0.0
    if ideal_low <= value <= ideal_high:
        return 100.0
    if value < ideal_low:
        return 100.0 * (value - low) / max(1e-9, ideal_low - low)
    return 100.0 * (high - value) / max(1e-9, high - ideal_high)


def ceiling_band_score(value: float, low: float, ideal: float) -> float:
    """Monotonic "more is better, capped" curve: 0 at/below low, linear to 100 at
    ideal and above.

    Use for expressive proxies where charisma *rises* with the metric up to a
    saturation point rather than peaking at a mid-range — e.g. pitch range,
    loudness (SPL) variation, and intonation modulations. The literature (Signorello
    on Steve Jobs; the cross-gender f0/SPL charisma study; Niebuhr "Winning Over an
    Audience"; the 2009 YouTube study) consistently finds wider f0 range and more
    intensity variation read as *more* charismatic, so a band that decays above a
    ceiling would punish exactly the expressive speech we want to reward."""
    if value <= low:
        return 0.0
    if value >= ideal:
        return 100.0
    return 100.0 * (value - low) / max(1e-9, ideal - low)


def inverse_band_score(value: float, good_max: float, bad_min: float) -> float:
    """For 'lower is better' metrics (e.g. jitter/shimmer perturbation): 100 at/below
    good_max, 0 at/above bad_min, linear in between."""
    if value <= good_max:
        return 100.0
    if value >= bad_min:
        return 0.0
    return 100.0 * (bad_min - value) / max(1e-9, bad_min - good_max)
