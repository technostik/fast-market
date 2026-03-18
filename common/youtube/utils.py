from __future__ import annotations

import re
from typing import Optional

from common import structlog

logger = structlog.get_logger(__name__)


def format_count(count: int) -> str:
    """Format a count number in K/M notation if > 1000."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 1000:
        return f"{count / 1000:.1f}K"
    return str(count)


def iso_duration_to_seconds(duration: str) -> int:
    """Convert ISO 8601 duration to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0
    return hours * 3600 + minutes * 60 + seconds


def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{int(secs):02d}"
    return f"{minutes}:{int(secs):02d}"


def is_short_video(duration: str) -> bool:
    """Determine if a video is a Short based on duration (≤60 seconds)."""
    total_seconds = iso_duration_to_seconds(duration)
    return total_seconds <= 60


def timecode_to_seconds(timecode: str) -> float:
    """Convert HH:MM:SS.mmm timecode to seconds."""
    parts = timecode.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_parts = parts[2].split(".")
        seconds = int(seconds_parts[0])
        milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    elif len(parts) == 2:
        minutes = int(parts[0])
        seconds_parts = parts[1].split(".")
        seconds = int(seconds_parts[0])
        milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
        return minutes * 60 + seconds + milliseconds / 1000
    else:
        seconds_parts = timecode.split(".")
        seconds = int(seconds_parts[0])
        milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
        return seconds + milliseconds / 1000


def parse_srt(srt_content: str) -> str:
    """Parse SRT caption content into plain text."""
    lines = srt_content.splitlines()
    transcript = []
    for line in lines:
        if (
            not line.strip()
            or re.match(r"\d+$", line)
            or re.match(r"\d{2}:\d{2}:\d{2},\d{3} -->", line)
        ):
            continue
        transcript.append(line.strip())
    return " ".join(transcript)
