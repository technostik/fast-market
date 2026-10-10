"""Open media whose container header has no duration.

Chrome MediaRecorder writes WebM with ``Duration: N/A``. MoviePy reads that
header and aborts. The packets still carry timestamps, so the duration is the
end of the shorter elementary stream.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def container_duration_seconds(path: str) -> float | None:
    """Return the container duration, or None when the header has none."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is not installed") from exc
    text = result.stdout.strip()
    if not text or text == "N/A":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _packet_end_seconds(path: str, stream: str) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", stream,
                "-show_entries", "packet=pts_time,duration_time",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True, text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is not installed") from exc
    end = None
    for line in result.stdout.splitlines():
        parts = line.strip().split(",")
        if not parts or not parts[0]:
            continue
        try:
            pts = float(parts[0])
        except ValueError:
            continue
        extra = 0.0
        if len(parts) > 1 and parts[1] not in ("", "N/A"):
            try:
                extra = float(parts[1])
            except ValueError:
                extra = 0.0
        if extra < 0:
            extra = 0.0
        edge = pts + extra
        end = edge if end is None else max(end, edge)
    return end if end is not None and end > 0 else None


def packet_span_seconds(path: str) -> float | None:
    """Duration from packet timestamps when the container header has none.

    Uses the shorter of the audio and video spans so a later frame read stays
    inside both streams.
    """
    ends = [
        end for end in (
            _packet_end_seconds(path, "v:0"),
            _packet_end_seconds(path, "a:0"),
        )
        if end is not None
    ]
    if not ends:
        return None
    return min(ends)


def _missing_container_duration(exc: BaseException) -> bool:
    return "Duration: N/A" in str(exc)


def _open_with_known_duration(filename: str, duration: float):
    import moviepy.audio.io.readers as audio_readers
    import moviepy.video.io.ffmpeg_reader as video_reader
    from moviepy import VideoFileClip

    original_video = video_reader.ffmpeg_parse_infos
    original_audio = audio_readers.ffmpeg_parse_infos

    def parse(filename, check_duration=True, fps_source="fps", decode_file=False, print_infos=False):
        infos = original_video(
            filename,
            check_duration=False,
            fps_source=fps_source,
            decode_file=False,
            print_infos=print_infos,
        )
        infos["duration"] = duration
        if infos.get("video_found"):
            infos["video_duration"] = duration
            infos["video_n_frames"] = int(duration * (infos.get("video_fps") or 0))
        return infos

    video_reader.ffmpeg_parse_infos = parse
    audio_readers.ffmpeg_parse_infos = parse
    try:
        return VideoFileClip(filename)
    finally:
        video_reader.ffmpeg_parse_infos = original_video
        audio_readers.ffmpeg_parse_infos = original_audio


def open_video_clip(filename: str):
    """Open ``filename`` with MoviePy, including Chrome WebM with no duration."""
    from moviepy import VideoFileClip

    try:
        return VideoFileClip(filename)
    except OSError as exc:
        if not _missing_container_duration(exc):
            raise
        print(
            f"Container duration is missing for {Path(filename).name}; "
            "reading packet timestamps...",
            file=sys.stderr,
        )
        duration = packet_span_seconds(filename)
        if duration is None:
            raise RuntimeError(
                f"ffmpeg reported Duration: N/A for {filename} and no packet "
                "timestamps were found. Remux the file with "
                "`ffmpeg -i INPUT -c copy OUTPUT.mkv` and retry."
            ) from exc
        return _open_with_known_duration(filename, duration)
