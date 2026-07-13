from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STEP_NAMES = [
    "Remove silence",
    "Extract transcript",
    "Generate title & description",
    "Generate thumbnail",
    "Append signature video",
    "Upload to YouTube",
]

DEFAULT_VIDEO_SOURCE_PATH = "/home/joriel/Vidéos"
DEFAULT_VIDEO_EXTENSIONS = "mp4,mkv"

_INTERMEDIATE_RE = re.compile(r"_(nosilence|subtitled|volume_normalized|with_signature)$", re.IGNORECASE)

# Output file keys surfaced per step in the UI (index aligns with STEP_NAMES).
_STEP_FILE_KEYS: list[list[str]] = [
    ["no_silence", "audio"],
    ["transcript", "transcript_txt"],
    ["final_video"],
    ["thumbnail"],
    ["final_video"],
    [],
]


@dataclass
class Step:
    name: str
    status: str = "pending"
    output: str = ""
    progress: float | None = None
    start_time: float | None = None
    end_time: float | None = None


@dataclass
class Job:
    job_id: str
    source: str
    prompt_title: str
    prompt_summary: str
    do_remove_silence: bool
    language: str
    model: str
    privacy: str
    transcript_mode: str = "normal"
    description_prefix: str = ""
    skip_upload: bool = False
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_add_signature: bool = True
    do_generate_thumbnail: bool = True
    source_urls: list[str] = field(default_factory=list)
    thumbnail_overlay_title: str = ""
    stop_requested: bool = False
    steps: list[Step] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    title: str = ""
    description: str = ""
    transcript_text: str = ""
    status: str = "running"
    video_url: str = ""
    studio_url: str = ""
    modal_url: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        job_elapsed = (self.end_time - self.start_time) if self.end_time else (now - self.start_time)
        return {
            "job_id": self.job_id,
            "source": self.source,
            "status": self.status,
            "video_url": self.video_url,
            "studio_url": self.studio_url,
            "modal_url": self.modal_url,
            "title": self.title,
            "description": self.description,
            "transcript_text": self.transcript_text,
            "files": self.files,
            "start_time": self.start_time,
            "elapsed_seconds": round(job_elapsed, 1),
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "output": s.output,
                    "progress": s.progress,
                    "start_time": s.start_time,
                    "elapsed_seconds": (
                        round(s.end_time - s.start_time, 1) if s.start_time and s.end_time
                        else round(now - s.start_time, 1) if s.start_time
                        else None
                    ),
                    "output_files": [
                        {"path": self.files[k], "name": Path(self.files[k]).name}
                        for k in _STEP_FILE_KEYS[i]
                        if k in self.files and self.files[k]
                    ],
                }
                for i, s in enumerate(self.steps)
            ],
        }
