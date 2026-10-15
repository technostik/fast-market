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
DEFAULT_VIDEO_EXTENSIONS = "mp4,mkv,webm"
LEGACY_VIDEO_EXTENSIONS = "mp4,mkv"

_INTERMEDIATE_RE = re.compile(r"_(nosilence|cut|subtitled|volume_normalized|no_signature)$", re.IGNORECASE)

# Output file keys surfaced per step in the UI (index aligns with STEP_NAMES).
_STEP_FILE_KEYS: list[list[str]] = [
    ["no_silence", "audio", "cut"],
    ["transcript", "transcript_txt", "transcript_json"],
    ["final_video"],
    ["thumbnail", "thumbnail_base"],
    ["final_video"],
    [],
]

# Step display names used when rhythm (transcript-first) mode is enabled.
# STEP_NAMES stays static (resume dropdowns and meta logs use indices).
RHYTHM_STEP_NAMES = [
    "Prepare audio",
    "Transcript + rhythm cut",
    "Generate title & description",
    "Generate thumbnail",
    "Append signature video",
    "Upload to YouTube",
]

# Rhythm tuning keys (publish config) mapped to video remove-silence flags.
# A key that is missing/empty in the publish config is NOT passed, so the
# video config file (or code default) applies. Set values override it.
RHYTHM_PARAM_FLAGS: dict[str, str] = {
    "rhythm_transcript_tolerance": "--transcript-tolerance",
    "rhythm_paragraph_threshold": "--paragraph-threshold",
    "rhythm_pause_inline": "--pause-inline",
    "rhythm_pause_comma": "--pause-comma",
    "rhythm_pause_sentence": "--pause-sentence",
    "rhythm_pause_paragraph": "--pause-paragraph",
    "rhythm_crossfade": "--crossfade",
}


def rhythm_params_from_pub(pub: dict) -> dict[str, float]:
    """Extract validated rhythm overrides from the publish config.

    Returns {config_key: value} for set values only. Raises ValueError on
    non-numeric or negative values.
    """
    params: dict[str, float] = {}
    for key in RHYTHM_PARAM_FLAGS:
        value = pub.get(key, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number >= 0, got {value!r}")
        if float(value) < 0:
            raise ValueError(f"{key} must be a number >= 0, got {value!r}")
        params[key] = float(value)
    return params


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
    rhythm_silence: bool = False
    rhythm_params: dict[str, float] = field(default_factory=dict)
    cut_time: str = ""
    transcript_mode: str = "normal"
    description_prefix: str = ""
    skip_upload: bool = False
    use_modal: bool = True
    do_normalize_volume: bool = False
    do_add_signature: bool = True
    do_generate_thumbnail: bool = True
    do_pinned_comment: bool = False
    pinned_comment_text: str = ""
    source_urls: list[str] = field(default_factory=list)
    thumbnail_overlay_title: str = ""
    thumbnail_prompt: str = ""
    thumbnail_engine: str = ""
    stop_requested: bool = False
    steps: list[Step] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    title: str = ""
    description: str = ""
    transcript_text: str = ""
    status: str = "running"
    video_url: str = ""
    studio_url: str = ""
    pinned_comment_id: str = ""
    pinned_comment_url: str = ""
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
            "pinned_comment_id": self.pinned_comment_id,
            "pinned_comment_url": self.pinned_comment_url,
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
