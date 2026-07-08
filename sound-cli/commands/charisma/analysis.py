from __future__ import annotations

import math

import librosa
import numpy as np

from commands.prosody.analysis import compute_f0_contour, score_prosody
from commands.scoring import ceiling_band_score, inverse_band_score, target_band_score

# Charisma-specific bands, heuristic targets informed by the general shape of
# findings in charismatic-speech research (Niebuhr, Signorello, Rodero et al.:
# more pitch movement, clearer/more resonant voice, and stable phonation read as
# more charismatic) — not literal thresholds lifted from any single paper.

# Direction reversals per voiced second in the F0 contour (dynamic rises/falls,
# distinct from PITCH_BAND's overall range in prosody/analysis.py). More modulations
# read as more charismatic (Niebuhr "Winning Over an Audience"), so this is a
# "more is better, capped" band: ceiling at ideal, not a mid-range peak. The
# threshold below is an absolute semitone movement (a clear pitch move), not a
# speaker-relative one — a relative threshold cancelled out the real difference
# between a narrower- and wider-range speaker.
MIN_REVERSAL_SEMITONES = 0.75
INTONATION_BAND = (0.3, 3.0)

# Spectral centroid (Hz) as a rough resonance/timbre proxy: too low reads dull/muffled,
# too high reads thin/harsh — a genuine mid-range optimum, so keep target_band_score.
RESONANCE_BAND = (300.0, 800.0, 2500.0, 4000.0)

# Harmonic-vs-percussive energy ratio (dB-like) from HPSS, as a rough clarity proxy —
# NOT a clinical Praat harmonics-to-noise ratio. For normal speech this proxy lands
# around 0 or slightly negative (percussive energy rivals harmonic), so the band must
# span negative values; higher (more harmonic) = clearer = more charismatic, capped.
HNR_BAND = (-15.0, 0.0)

# Relative frame-to-frame perturbation of F0 / RMS, as rough jitter/shimmer proxies —
# NOT pitch-period-synchronous clinical jitter/shimmer percentages.
JITTER_GOOD_MAX, JITTER_BAD_MIN = 0.02, 0.12
SHIMMER_GOOD_MAX, SHIMMER_BAD_MIN = 0.15, 0.60

PROSODY_WEIGHT = 0.70
VOICE_QUALITY_WEIGHT = 0.20
OTHER_WEIGHT = 0.10


def analyze_intonation(y: np.ndarray, sr: int) -> dict:
    f0, voiced_flag = compute_f0_contour(y, sr)
    if f0 is None:
        return {"reversals_per_sec": 0.0}

    voiced_f0 = f0[voiced_flag & ~np.isnan(f0)]
    if voiced_f0.size < 3:
        return {"reversals_per_sec": 0.0}

    # Smooth the contour to suppress per-frame pyin jitter, which otherwise reads as
    # ~6 fake direction reversals/sec even in a monotone voice. After smoothing we
    # count meaningful modulations against an absolute semitone threshold, not noise flips.
    win = max(3, int(round(0.05 * sr / 512)))  # ~50 ms window (librosa.pyin hop = 512)
    smoothed = (
        np.convolve(voiced_f0, np.ones(win) / win, mode="same")
        if voiced_f0.size >= win
        else voiced_f0
    )

    semitone_diffs = 12 * np.log2(smoothed[1:] / smoothed[:-1])
    direction = np.sign(np.where(np.abs(semitone_diffs) >= MIN_REVERSAL_SEMITONES, semitone_diffs, 0.0))
    direction = direction[direction != 0]
    if direction.size < 2:
        return {"reversals_per_sec": 0.0}

    reversals = int(np.sum(direction[1:] != direction[:-1]))
    frame_hop_secs = 512 / sr  # librosa.pyin default hop_length
    voiced_secs = voiced_f0.size * frame_hop_secs
    reversals_per_sec = (reversals / voiced_secs) if voiced_secs > 0 else 0.0

    return {"reversals_per_sec": float(reversals_per_sec)}


def analyze_voice_quality(y: np.ndarray, sr: int) -> dict:
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))

    y_harmonic, y_percussive = librosa.effects.hpss(y)
    harmonic_energy = float(np.sum(y_harmonic**2))
    percussive_energy = float(np.sum(y_percussive**2))
    hnr_proxy_db = 10 * math.log10(harmonic_energy / max(percussive_energy, 1e-9)) if harmonic_energy > 0 else 0.0

    f0, voiced_flag = compute_f0_contour(y, sr)
    voiced_f0 = f0[voiced_flag & ~np.isnan(f0)] if f0 is not None else np.array([])
    if voiced_f0.size >= 2 and np.mean(voiced_f0) > 0:
        jitter_proxy = float(np.mean(np.abs(np.diff(voiced_f0))) / np.mean(voiced_f0))
    else:
        jitter_proxy = 0.0

    rms = librosa.feature.rms(y=y)[0]
    if rms.size >= 2 and np.mean(rms) > 0:
        shimmer_proxy = float(np.mean(np.abs(np.diff(rms))) / np.mean(rms))
    else:
        shimmer_proxy = 0.0

    return {
        "spectral_centroid_hz": centroid,
        "hnr_proxy_db": hnr_proxy_db,
        "jitter_proxy": jitter_proxy,
        "shimmer_proxy": shimmer_proxy,
    }


def _normal_cdf(x: float, mean: float, sd: float) -> float:
    return 0.5 * (1 + math.erf((x - mean) / (sd * math.sqrt(2))))


def _build_notes(scores: dict[str, float]) -> str:
    strengths = sorted(((v, k) for k, v in scores.items() if v >= 75), reverse=True)[:2]
    weaknesses = sorted((v, k) for k, v in scores.items() if v <= 35)[:2]
    parts = []
    if strengths:
        parts.append("strengths: " + ", ".join(k for _, k in strengths))
    if weaknesses:
        parts.append("weaknesses: " + ", ".join(k for _, k in weaknesses))
    return "; ".join(parts) if parts else "no strong outliers"


def score_charisma(y: np.ndarray, sr: int) -> dict:
    prosody = score_prosody(y, sr)
    intonation = analyze_intonation(y, sr)
    voice = analyze_voice_quality(y, sr)

    intonation_score = ceiling_band_score(intonation["reversals_per_sec"], *INTONATION_BAND)
    resonance_score = target_band_score(voice["spectral_centroid_hz"], *RESONANCE_BAND)
    hnr_score = ceiling_band_score(voice["hnr_proxy_db"], *HNR_BAND)
    jitter_score = inverse_band_score(voice["jitter_proxy"], JITTER_GOOD_MAX, JITTER_BAD_MIN)
    shimmer_score = inverse_band_score(voice["shimmer_proxy"], SHIMMER_GOOD_MAX, SHIMMER_BAD_MIN)
    stability_score = (jitter_score + shimmer_score) / 2

    # Prosody & Acoustic Features (70%): pitch/energy/rhythm/rate come straight from
    # sound prosody, plus intonation dynamism specific to charisma.
    prosody_features_score = (
        prosody["pitch_score"] + prosody["energy_score"] + prosody["rhythm_score"]
        + prosody["rate_score"] + intonation_score
    ) / 5

    # Voice Quality (20%): resonance, harmonic clarity, phonation stability.
    voice_quality_score = (resonance_score + hnr_score + stability_score) / 3

    # Other Factors (10%): expressiveness/confidence/engagement have no independent
    # acoustic measurement here — this is a derived composite of the dynamism-related
    # subscores above, not a separately measured dimension.
    other_score = (intonation_score + prosody["energy_score"] + prosody["rate_score"]) / 3

    charisma_score = (
        PROSODY_WEIGHT * prosody_features_score
        + VOICE_QUALITY_WEIGHT * voice_quality_score
        + OTHER_WEIGHT * other_score
    )

    notes = _build_notes({
        "pitch variation": prosody["pitch_score"],
        "loudness dynamics": prosody["energy_score"],
        "pausing/rhythm": prosody["rhythm_score"],
        "speaking rate": prosody["rate_score"],
        "intonation dynamism": intonation_score,
        "vocal resonance": resonance_score,
        "harmonic clarity": hnr_score,
        "voice stability": stability_score,
    })

    # Rough illustrative percentile assuming charisma scores are ~N(50, 15) across
    # speakers in general. Not derived from any validated normative dataset.
    percentile_estimate = round(_normal_cdf(charisma_score, mean=50.0, sd=15.0) * 100, 1)

    return {
        "charisma_score": round(charisma_score, 1),
        "prosody_features_score": round(prosody_features_score, 1),
        "voice_quality_score": round(voice_quality_score, 1),
        "other_score": round(other_score, 1),
        "pitch_score": prosody["pitch_score"],
        "energy_score": prosody["energy_score"],
        "rhythm_score": prosody["rhythm_score"],
        "rate_score": prosody["rate_score"],
        "intonation_score": round(intonation_score, 1),
        "resonance_score": round(resonance_score, 1),
        "hnr_score": round(hnr_score, 1),
        "stability_score": round(stability_score, 1),
        "duration_secs": prosody["duration_secs"],
        "percentile_estimate": percentile_estimate,
        "notes": notes,
        # Raw underlying metrics behind the subscores above — useful for direct
        # comparison between recordings (e.g. "my median pitch vs. theirs in Hz"),
        # not just the normalized 0-100 scores.
        "median_f0_hz": prosody["median_f0_hz"],
        "semitone_range": prosody["semitone_range"],
        "rms_cv": prosody["rms_cv"],
        "pause_count_per_min": prosody["pause_count_per_min"],
        "estimated_rate_per_sec": prosody["estimated_rate_per_sec"],
        "reversals_per_sec": round(intonation["reversals_per_sec"], 2),
        "spectral_centroid_hz": round(voice["spectral_centroid_hz"], 1),
        "hnr_proxy_db": round(voice["hnr_proxy_db"], 1),
        "jitter_proxy": round(voice["jitter_proxy"], 4),
        "shimmer_proxy": round(voice["shimmer_proxy"], 4),
    }
