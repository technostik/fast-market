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
