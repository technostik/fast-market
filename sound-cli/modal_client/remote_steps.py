from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import modal
import numpy as np
from modal_client.app import app, base_image

# ── helpers ────────────────────────────────────────────────────────────────────

TARGET_SR = 22050
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"})

_MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def target_band_score(value: float, low: float, ideal_low: float, ideal_high: float, high: float) -> float:
    if value <= low or value >= high:
        return 0.0
    if ideal_low <= value <= ideal_high:
        return 100.0
    if value < ideal_low:
        return 100.0 * (value - low) / max(1e-9, ideal_low - low)
    return 100.0 * (high - value) / max(1e-9, high - ideal_high)


def inverse_band_score(value: float, good_max: float, bad_min: float) -> float:
    if value <= good_max:
        return 100.0
    if value >= bad_min:
        return 0.0
    return 100.0 * (bad_min - value) / max(1e-9, bad_min - good_max)


# ── prosody analysis ──────────────────────────────────────────────────────────

def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    import librosa
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", str(TARGET_SR), tmp_path],
                check=True, capture_output=True,
            )
            y, sr = librosa.load(tmp_path, sr=TARGET_SR, mono=True)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    else:
        y, sr = librosa.load(str(path), sr=TARGET_SR, mono=True)
    if y.size == 0:
        raise ValueError(f"No audio samples decoded from {path}")
    return y, sr


def _compute_f0_contour(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    import librosa
    f0, voiced_flag, _ = librosa.pyin(
        y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C6"), sr=sr,
    )
    return f0, voiced_flag


def _analyze_pitch(y: np.ndarray, sr: int) -> dict:
    f0, voiced_flag = _compute_f0_contour(y, sr)
    voiced = f0[voiced_flag & ~np.isnan(f0)] if f0 is not None else np.array([])
    if voiced.size == 0:
        return {"median_f0_hz": None, "semitone_range": 0.0}
    median_f0 = float(np.median(voiced))
    f_lo, f_hi = np.percentile(voiced, [5, 95])
    semitone_range = float(12 * np.log2(f_hi / f_lo)) if f_lo > 0 else 0.0
    return {"median_f0_hz": median_f0, "semitone_range": semitone_range}


def _analyze_energy(y: np.ndarray) -> dict:
    import librosa
    rms = librosa.feature.rms(y=y)[0]
    mean = float(rms.mean())
    std = float(rms.std())
    rms_cv = (std / mean) if mean > 0 else 0.0
    return {"rms_cv": rms_cv}


def _analyze_rhythm(y: np.ndarray, sr: int) -> dict:
    import librosa
    total_secs = len(y) / sr
    intervals = librosa.effects.split(y, top_db=30)
    if len(intervals) == 0:
        return {"intervals": intervals, "pause_ratio": 1.0, "pause_count_per_min": 0.0}
    speech_secs = sum((end - start) for start, end in intervals) / sr
    pause_ratio = max(0.0, (total_secs - speech_secs) / total_secs) if total_secs > 0 else 0.0
    pause_durations = [
        (intervals[i + 1][0] - intervals[i][1]) / sr
        for i in range(len(intervals) - 1)
    ]
    pause_durations = [d for d in pause_durations if d >= 0.15]
    pause_count_per_min = (len(pause_durations) / (total_secs / 60)) if total_secs > 0 else 0.0
    return {"intervals": intervals, "pause_ratio": pause_ratio, "pause_count_per_min": pause_count_per_min}


def _analyze_rate(y: np.ndarray, sr: int, intervals: np.ndarray) -> dict:
    import librosa
    if len(intervals) == 0:
        return {"rate_per_sec": 0.0}
    speech_y = np.concatenate([y[start:end] for start, end in intervals])
    speech_secs = len(speech_y) / sr
    if speech_secs <= 0:
        return {"rate_per_sec": 0.0}
    onset_times = librosa.onset.onset_detect(y=speech_y, sr=sr, units="time")
    rate_per_sec = float(len(onset_times) / speech_secs)
    return {"rate_per_sec": rate_per_sec}


PITCH_BAND = (1.0, 4.0, 12.0, 20.0)
ENERGY_BAND = (0.10, 0.30, 0.70, 1.20)
RHYTHM_BAND = (0.02, 0.10, 0.30, 0.55)
RATE_BAND = (1.0, 3.0, 6.0, 9.0)
PITCH_WEIGHT = 0.3
RHYTHM_WEIGHT = 0.3
RATE_WEIGHT = 0.2
ENERGY_WEIGHT = 0.2


def _score_prosody(y: np.ndarray, sr: int) -> dict:
    pitch = _analyze_pitch(y, sr)
    energy = _analyze_energy(y)
    rhythm = _analyze_rhythm(y, sr)
    rate = _analyze_rate(y, sr, rhythm["intervals"])

    pitch_score = target_band_score(pitch["semitone_range"], *PITCH_BAND)
    energy_score = target_band_score(energy["rms_cv"], *ENERGY_BAND)
    rhythm_score = target_band_score(rhythm["pause_ratio"], *RHYTHM_BAND)
    rate_score = target_band_score(rate["rate_per_sec"], *RATE_BAND)

    global_score = (
        PITCH_WEIGHT * pitch_score
        + RHYTHM_WEIGHT * rhythm_score
        + RATE_WEIGHT * rate_score
        + ENERGY_WEIGHT * energy_score
    )

    return {
        "global_score": round(global_score, 1),
        "pitch_score": round(pitch_score, 1),
        "energy_score": round(energy_score, 1),
        "rhythm_score": round(rhythm_score, 1),
        "rate_score": round(rate_score, 1),
        "duration_secs": round(len(y) / sr, 2),
        "median_f0_hz": round(pitch["median_f0_hz"], 1) if pitch["median_f0_hz"] is not None else None,
        "semitone_range": round(pitch["semitone_range"], 2),
        "rms_cv": round(energy["rms_cv"], 3),
        "pause_count_per_min": round(rhythm["pause_count_per_min"], 1),
        "estimated_rate_per_sec": round(rate["rate_per_sec"], 2),
    }


# ── charisma analysis ─────────────────────────────────────────────────────────

MIN_REVERSAL_SEMITONES = 0.5
INTONATION_BAND = (0.3, 1.0, 3.0, 5.0)
RESONANCE_BAND = (300.0, 800.0, 2500.0, 4000.0)
HNR_BAND = (0.0, 6.0, 20.0, 30.0)
JITTER_GOOD_MAX, JITTER_BAD_MIN = 0.02, 0.12
SHIMMER_GOOD_MAX, SHIMMER_BAD_MIN = 0.15, 0.60
PROSODY_WEIGHT = 0.70
VOICE_QUALITY_WEIGHT = 0.20
OTHER_WEIGHT = 0.10


def _analyze_intonation(f0: np.ndarray | None, voiced_flag: np.ndarray | None, sr: int) -> dict:
    if f0 is None:
        return {"reversals_per_sec": 0.0}
    voiced_f0 = f0[voiced_flag & ~np.isnan(f0)]
    if voiced_f0.size < 3:
        return {"reversals_per_sec": 0.0}
    semitone_diffs = 12 * np.log2(voiced_f0[1:] / voiced_f0[:-1])
    direction = np.sign(np.where(np.abs(semitone_diffs) >= MIN_REVERSAL_SEMITONES, semitone_diffs, 0.0))
    direction = direction[direction != 0]
    if direction.size < 2:
        return {"reversals_per_sec": 0.0}
    reversals = int(np.sum(direction[1:] != direction[:-1]))
    frame_hop_secs = 512 / sr
    voiced_secs = voiced_f0.size * frame_hop_secs
    reversals_per_sec = (reversals / voiced_secs) if voiced_secs > 0 else 0.0
    return {"reversals_per_sec": float(reversals_per_sec)}


def _analyze_voice_quality(y: np.ndarray, sr: int, f0: np.ndarray | None, voiced_flag: np.ndarray | None) -> dict:
    import librosa
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    y_harmonic, y_percussive = librosa.effects.hpss(y)
    harmonic_energy = float(np.sum(y_harmonic**2))
    percussive_energy = float(np.sum(y_percussive**2))
    hnr_proxy_db = 10 * math.log10(harmonic_energy / max(percussive_energy, 1e-9)) if harmonic_energy > 0 else 0.0
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


def _score_charisma(y: np.ndarray, sr: int) -> dict:
    prosody = _score_prosody(y, sr)
    f0, voiced_flag = _compute_f0_contour(y, sr)
    intonation = _analyze_intonation(f0, voiced_flag, sr)
    voice = _analyze_voice_quality(y, sr, f0, voiced_flag)

    intonation_score = target_band_score(intonation["reversals_per_sec"], *INTONATION_BAND)
    resonance_score = target_band_score(voice["spectral_centroid_hz"], *RESONANCE_BAND)
    hnr_score = target_band_score(voice["hnr_proxy_db"], *HNR_BAND)
    jitter_score = inverse_band_score(voice["jitter_proxy"], JITTER_GOOD_MAX, JITTER_BAD_MIN)
    shimmer_score = inverse_band_score(voice["shimmer_proxy"], SHIMMER_GOOD_MAX, SHIMMER_BAD_MIN)
    stability_score = (jitter_score + shimmer_score) / 2

    prosody_features_score = (
        prosody["pitch_score"] + prosody["energy_score"] + prosody["rhythm_score"]
        + prosody["rate_score"] + intonation_score
    ) / 5

    voice_quality_score = (resonance_score + hnr_score + stability_score) / 3

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


# ── normalize-volume helpers ──────────────────────────────────────────────────

THRESHOLD_DB = -30
RATIO = 4
ATTACK_MS = 20
RELEASE_MS = 200
MAKEUP_MIN = 1.0
MAKEUP_MAX = 64.0
CORRECTION_TOLERANCE_DB = 0.5


def _measure_mean_volume(path: Path) -> float:
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = _MEAN_VOLUME_RE.search(result.stderr)
    if not match:
        raise ValueError(f"Could not determine mean volume of {path}")
    return float(match.group(1))


def _compute_makeup_gain(target_dbfs: float, input_dbfs: float) -> float:
    gain_db = target_dbfs - input_dbfs
    makeup_linear = 10 ** (gain_db / 20)
    return max(MAKEUP_MIN, min(MAKEUP_MAX, makeup_linear))


def _residual_correction_gain(target_dbfs: float, actual_dbfs: float) -> float | None:
    residual = target_dbfs - actual_dbfs
    return residual if abs(residual) > CORRECTION_TOLERANCE_DB else None


def _apply_dynamic_normalization(input_path: Path, output_path: Path, makeup_gain: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    compressor = (
        f"acompressor=threshold={THRESHOLD_DB}dB:ratio={RATIO}:"
        f"attack={ATTACK_MS}:release={RELEASE_MS}:makeup={makeup_gain}"
    )
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", compressor,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalization failed: {result.stderr[-800:]}")


def _apply_flat_gain(input_path: Path, output_path: Path, gain_db: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", f"volume={gain_db}dB,alimiter=limit=0.891:level=false",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg gain correction failed: {result.stderr[-800:]}")


# ── Remote entry points ───────────────────────────────────────────────────────


@app.function(image=base_image, timeout=600)
def remote_charisma(file_bytes: bytes, file_name: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, file_name)
        with open(input_path, "wb") as f:
            f.write(file_bytes)
        y, sr = _load_audio(Path(input_path))
        return _score_charisma(y, sr)


@app.function(image=base_image, timeout=600)
def remote_normalize_volume_measure(file_bytes: bytes, file_name: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, file_name)
        with open(input_path, "wb") as f:
            f.write(file_bytes)
        mean_db = _measure_mean_volume(Path(input_path))
        return {"path": file_name, "mean_volume_db": mean_db}


@app.function(image=base_image, timeout=600)
def remote_normalize_volume_apply(file_bytes: bytes, file_name: str, target_db: float) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        stem = Path(file_name).stem
        ext = Path(file_name).suffix
        input_path = os.path.join(tmpdir, file_name)
        output_path = os.path.join(tmpdir, f"{stem}_normalized{ext}")

        with open(input_path, "wb") as f:
            f.write(file_bytes)

        current_db = _measure_mean_volume(Path(input_path))
        makeup_gain = _compute_makeup_gain(target_db, current_db)
        _apply_dynamic_normalization(Path(input_path), Path(output_path), makeup_gain)
        output_db = _measure_mean_volume(Path(output_path))

        correction_db = _residual_correction_gain(target_db, output_db)
        if correction_db is not None:
            corrected_path = os.path.join(tmpdir, f".{stem}.correcting{ext}")
            _apply_flat_gain(Path(output_path), Path(corrected_path), correction_db)
            os.replace(corrected_path, output_path)
            output_db = _measure_mean_volume(Path(output_path))

        with open(output_path, "rb") as f:
            out_bytes = f.read()

        return {
            "output_bytes": out_bytes,
            "input_volume_db": current_db,
            "target_db": target_db,
            "makeup_gain": makeup_gain,
            "correction_db": correction_db,
            "output_volume_db": output_db,
        }
