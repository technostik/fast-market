from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_FOLDER = "/home/joriel/Vidéos/Shorts"

VIDEO_EXTENSIONS = {"mp4", "mov", "mkv", "avi", "webm", "m4v"}
AUDIO_EXTENSIONS = {"wav", "mp3", "flac", "ogg", "m4a", "aac"}
DEFAULT_EXTENSIONS = ",".join(sorted(VIDEO_EXTENSIONS | AUDIO_EXTENSIONS))


def file_kind(suffix: str) -> str:
    return "video" if suffix.lower().lstrip(".") in VIDEO_EXTENSIONS else "audio"


@dataclass
class FileResult:
    path: str
    name: str
    kind: str  # "video" | "audio"
    status: str = "pending"  # pending | running | done | error
    error: str | None = None
    scores: dict[str, Any] | None = None  # full `sound charisma --format json` output
    cached: bool = False  # scores came from the folder's .charisma-scores.json, not a fresh run

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "error": self.error,
            "cached": self.cached,
        }
        if self.scores:
            d.update(self.scores)
        return d


@dataclass
class ScanJob:
    job_id: str
    folder: str
    files: list[FileResult] = field(default_factory=list)
    status: str = "running"  # running | done
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        total = len(self.files)
        completed = sum(1 for f in self.files if f.status in ("done", "error"))
        elapsed = (self.end_time or now) - self.start_time
        avg_per_file = (elapsed / completed) if completed else 0.0
        eta_seconds = round(avg_per_file * (total - completed), 1) if self.status == "running" and completed else 0.0

        return {
            "job_id": self.job_id,
            "folder": self.folder,
            "status": self.status,
            "total": total,
            "completed": completed,
            "progress": round(100 * completed / total, 1) if total else 100.0,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": eta_seconds,
            "files": [f.to_dict() for f in self.files],
        }
