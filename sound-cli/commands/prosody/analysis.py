from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import click
import librosa
import numpy as np

from commands.scoring import target_band_score as _target_band_score

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
TARGET_SR = 22050

# Minimum gap between voiced segments to count as a deliberate pause,
# rather than a brief dip inside a word (librosa.effects.split jitter).
MIN_PAUSE_SECS = 0.15
SILENCE_TOP_DB = 30

# Each band is (low, ideal_low, ideal_high, high): score is 100 inside
# [ideal_low, ideal_high], 0 at/beyond low or high, linear in between.
# Bands are heuristic targets for expressive human speech, not hard science.
PITCH_BAND = (1.0, 4.0, 12.0, 20.0)          # semitone range (5th-95th pct F0)
ENERGY_BAND = (0.10, 0.30, 0.70, 1.20)       # RMS coefficient of variation
RHYTHM_BAND = (0.02, 0.10, 0.30, 0.55)       # silence ratio of total duration
RATE_BAND = (1.0, 3.0, 6.0, 9.0)             # onsets/sec (syllable-rate proxy)

PITCH_WEIGHT = 0.3
RHYTHM_WEIGHT = 0.3
RATE_WEIGHT = 0.2
ENERGY_WEIGHT = 0.2


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Load mono audio at TARGET_SR, extracting from video via ffmpeg if needed."""
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        if not shutil.which("ffmpeg"):
            raise click.ClickException("ffmpeg not found on PATH (required to extract audio from video).")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", str(TARGET_SR), tmp_path],
                check=True, capture_output=True,
            )
            y, sr = librosa.load(tmp_path, sr=TARGET_SR, mono=True)
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if e.stderr else ""
            raise click.ClickException(f"ffmpeg audio extraction failed: {stderr[-500:]}") from e
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    else:
        y, sr = librosa.load(str(path), sr=TARGET_SR, mono=True)

    if y.size == 0:
        raise click.ClickException(f"No audio samples decoded from {path}")

    return y, sr


def compute_f0_contour(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Shared pitch tracker: returns (f0, voiced_flag) from librosa.pyin, reused by
    both prosody and charisma analysis so pyin only runs once per concern."""
    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sr,
    )
    return f0, voiced_flag


def analyze_pitch(y: np.ndarray, sr: int) -> dict:
    f0, voiced_flag = compute_f0_contour(y, sr)
    voiced = f0[voiced_flag & ~np.isnan(f0)] if f0 is not None else np.array([])

    if voiced.size == 0:
        return {"median_f0_hz": None, "semitone_range": 0.0}

    median_f0 = float(np.median(voiced))
    f_lo, f_hi = np.percentile(voiced, [5, 95])
    semitone_range = float(12 * np.log2(f_hi / f_lo)) if f_lo > 0 else 0.0

    return {"median_f0_hz": median_f0, "semitone_range": semitone_range}


def analyze_energy(y: np.ndarray, sr: int) -> dict:
    rms = librosa.feature.rms(y=y)[0]
    mean = float(rms.mean())
    std = float(rms.std())
    rms_cv = (std / mean) if mean > 0 else 0.0
    return {"rms_cv": rms_cv}


def analyze_rhythm(y: np.ndarray, sr: int) -> dict:
    total_secs = len(y) / sr
    intervals = librosa.effects.split(y, top_db=SILENCE_TOP_DB)

    if len(intervals) == 0:
        return {"intervals": intervals, "pause_ratio": 1.0, "pause_count_per_min": 0.0}

    speech_secs = sum((end - start) for start, end in intervals) / sr
    pause_ratio = max(0.0, (total_secs - speech_secs) / total_secs) if total_secs > 0 else 0.0

    pause_durations = [
        (intervals[i + 1][0] - intervals[i][1]) / sr
        for i in range(len(intervals) - 1)
    ]
    pause_durations = [d for d in pause_durations if d >= MIN_PAUSE_SECS]
    pause_count_per_min = (len(pause_durations) / (total_secs / 60)) if total_secs > 0 else 0.0

    return {
        "intervals": intervals,
        "pause_ratio": pause_ratio,
        "pause_count_per_min": pause_count_per_min,
    }


def analyze_rate(y: np.ndarray, sr: int, intervals: np.ndarray) -> dict:
    if len(intervals) == 0:
        return {"rate_per_sec": 0.0}

    speech_y = np.concatenate([y[start:end] for start, end in intervals])
    speech_secs = len(speech_y) / sr
    if speech_secs <= 0:
        return {"rate_per_sec": 0.0}

    onset_times = librosa.onset.onset_detect(y=speech_y, sr=sr, units="time")
    rate_per_sec = float(len(onset_times) / speech_secs)
    return {"rate_per_sec": rate_per_sec}


def score_prosody(y: np.ndarray, sr: int) -> dict:
    pitch = analyze_pitch(y, sr)
    energy = analyze_energy(y, sr)
    rhythm = analyze_rhythm(y, sr)
    rate = analyze_rate(y, sr, rhythm["intervals"])

    pitch_score = _target_band_score(pitch["semitone_range"], *PITCH_BAND)
    energy_score = _target_band_score(energy["rms_cv"], *ENERGY_BAND)
    rhythm_score = _target_band_score(rhythm["pause_ratio"], *RHYTHM_BAND)
    rate_score = _target_band_score(rate["rate_per_sec"], *RATE_BAND)

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
