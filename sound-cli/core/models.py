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
