from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TTSRequest:
    text: str
    engine: str
    voice: str
    speed: float = 1.0
    language: str = "English"


@dataclass
class TTSResult:
    path: Path
    text: str
    voice: str
    engine: str
    duration_secs: float
    sample_rate: int

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "text": self.text,
            "voice": self.voice,
            "engine": self.engine,
            "duration_secs": self.duration_secs,
            "sample_rate": self.sample_rate,
        }


@dataclass
class MusicGenResult:
    path: Path
    prompt: str
    engine: str
    duration_secs: float
    sample_rate: int

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "prompt": self.prompt,
            "engine": self.engine,
            "duration_secs": self.duration_secs,
            "sample_rate": self.sample_rate,
        }


@dataclass
class ProsodyResult:
    path: Path
    global_score: float
    pitch_score: float
    energy_score: float
    rhythm_score: float
    rate_score: float
    duration_secs: float
    median_f0_hz: float | None
    semitone_range: float
    rms_cv: float
    pause_count_per_min: float
    estimated_rate_per_sec: float

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "global_score": self.global_score,
            "pitch_score": self.pitch_score,
            "energy_score": self.energy_score,
            "rhythm_score": self.rhythm_score,
            "rate_score": self.rate_score,
            "duration_secs": self.duration_secs,
            "median_f0_hz": self.median_f0_hz,
            "semitone_range": self.semitone_range,
            "rms_cv": self.rms_cv,
            "pause_count_per_min": self.pause_count_per_min,
            "estimated_rate_per_sec": self.estimated_rate_per_sec,
        }


@dataclass
class CharismaResult:
    path: Path
    charisma_score: float
    prosody_features_score: float
    voice_quality_score: float
    other_score: float
    pitch_score: float
    energy_score: float
    rhythm_score: float
    rate_score: float
    intonation_score: float
    resonance_score: float
    hnr_score: float
    stability_score: float
    duration_secs: float
    percentile_estimate: float
    notes: str
    median_f0_hz: float | None
    semitone_range: float
    rms_cv: float
    pause_count_per_min: float
    estimated_rate_per_sec: float
    reversals_per_sec: float
    spectral_centroid_hz: float
    hnr_proxy_db: float
    jitter_proxy: float
    shimmer_proxy: float

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "charisma_score": self.charisma_score,
            "prosody_features_score": self.prosody_features_score,
            "voice_quality_score": self.voice_quality_score,
            "other_score": self.other_score,
            "pitch_score": self.pitch_score,
            "energy_score": self.energy_score,
            "rhythm_score": self.rhythm_score,
            "rate_score": self.rate_score,
            "intonation_score": self.intonation_score,
            "resonance_score": self.resonance_score,
            "hnr_score": self.hnr_score,
            "stability_score": self.stability_score,
            "duration_secs": self.duration_secs,
            "percentile_estimate": self.percentile_estimate,
            "notes": self.notes,
            "median_f0_hz": self.median_f0_hz,
            "semitone_range": self.semitone_range,
            "rms_cv": self.rms_cv,
            "pause_count_per_min": self.pause_count_per_min,
            "estimated_rate_per_sec": self.estimated_rate_per_sec,
            "reversals_per_sec": self.reversals_per_sec,
            "spectral_centroid_hz": self.spectral_centroid_hz,
            "hnr_proxy_db": self.hnr_proxy_db,
            "jitter_proxy": self.jitter_proxy,
            "shimmer_proxy": self.shimmer_proxy,
        }
