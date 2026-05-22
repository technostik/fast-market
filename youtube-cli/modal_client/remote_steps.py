from __future__ import annotations

import modal
from modal_client.app import app, base_image


@app.function(image=base_image, timeout=1800)
def run_media_pipeline(
    video_bytes: bytes,
    video_name: str,
    do_remove_silence: bool = True,
    threshold: float = -65.0,
    do_transcribe: bool = True,
    ass_bytes: bytes | None = None,
    do_burn_subtitles: bool = True,
    language: str = "fr",
    model_size: str = "medium",
    subtitle_size: int = 96,
) -> dict:
    """
    Run up to three media processing steps inside one Modal container:
      0. Remove silence (moviepy)
      1. Transcribe to ASS karaoke (faster-whisper)
      2. Burn subtitles (ffmpeg)

    Pass ass_bytes + do_transcribe=False to skip transcription and use an
    existing subtitle file (resume-from-step-2 case).

    Returns:
      video_bytes      - final processed video
      video_name       - filename of the output video
      ass_bytes        - ASS subtitle file bytes (empty if not produced)
      ass_txt          - plain-text transcript (empty if not produced)
      original_duration - seconds before silence removal (None if skipped)
      final_duration   - seconds after silence removal (None if skipped)
    """
    import os
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        stem = Path(video_name).stem

        input_path = os.path.join(tmpdir, video_name)
        with open(input_path, "wb") as f:
            f.write(video_bytes)

        current_path = input_path
        original_duration = None
        final_duration = None

        # ── Step 0: Remove silence ────────────────────────────────────────────
        if do_remove_silence:
            out_path = os.path.join(tmpdir, f"{stem}_nosilence.mp4")
            current_path, original_duration, final_duration = _remove_silence(
                current_path, out_path, threshold
            )

        # ── Step 1: Transcribe → ASS ──────────────────────────────────────────
        ass_path = os.path.join(tmpdir, f"{stem}.ass")
        if do_transcribe:
            _transcribe_to_ass(current_path, ass_path, language, model_size)
        elif ass_bytes:
            with open(ass_path, "wb") as f:
                f.write(ass_bytes)

        # ── Step 2: Burn subtitles ────────────────────────────────────────────
        if do_burn_subtitles and os.path.exists(ass_path):
            out_path = os.path.join(tmpdir, f"{stem}_subtitled.mp4")
            _burn_subtitles(current_path, ass_path, out_path, subtitle_size)
            current_path = out_path

        # ── Collect outputs ───────────────────────────────────────────────────
        with open(current_path, "rb") as f:
            out_video_bytes = f.read()

        out_ass_bytes = b""
        if os.path.exists(ass_path):
            with open(ass_path, "rb") as f:
                out_ass_bytes = f.read()

        ass_txt = _ass_to_plain_text(out_ass_bytes.decode("utf-8", errors="replace")) if out_ass_bytes else ""

        return {
            "video_bytes": out_video_bytes,
            "video_name": Path(current_path).name,
            "ass_bytes": out_ass_bytes,
            "ass_txt": ass_txt,
            "original_duration": original_duration,
            "final_duration": final_duration,
        }


# ── Helpers (run on the Modal worker) ────────────────────────────────────────

def _remove_silence(
    input_path: str,
    output_path: str,
    threshold: float,
) -> tuple[str, float, float]:
    import numpy as np
    from moviepy import VideoFileClip, concatenate_videoclips

    video = VideoFileClip(input_path)
    original_duration = video.duration
    audio_array = video.audio.to_soundarray(fps=video.audio.fps)
    if len(audio_array.shape) > 1:
        audio_array = np.mean(audio_array, axis=1).astype(np.float32)

    segments = _detect_silence_segments(audio_array, video.audio.fps, threshold)
    if not segments:
        video.close()
        raise RuntimeError("No non-silent segments detected — check threshold")

    clips = [video.subclipped(start, end) for start, end in segments]
    final = concatenate_videoclips(clips)

    import os
    temp_audio = os.path.join(os.path.dirname(os.path.abspath(output_path)), "temp-audio.m4a")
    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=temp_audio,
        remove_temp=True,
        audio_bitrate="192k",
        preset="medium",
    )
    final_duration = final.duration
    video.close()
    final.close()
    for c in clips:
        c.close()
    return output_path, original_duration, final_duration


def _detect_silence_segments(
    audio_array,
    sample_rate: int,
    threshold_db: float,
) -> list[tuple[float, float]]:
    import numpy as np

    threshold_amp = 10 ** (threshold_db / 20)
    window_size = int(sample_rate / 30)
    if window_size == 0:
        return []
    num_windows = len(audio_array) // window_size
    if num_windows == 0:
        return []
    audio_array = audio_array[: num_windows * window_size]
    rms = np.array([
        np.sqrt(np.mean(w ** 2))
        for w in np.array_split(audio_array, num_windows)
    ])
    is_non_silent = rms >= threshold_amp
    time_per_window = window_size / sample_rate
    segments: list[tuple[float, float]] = []
    start_idx = None
    for i, active in enumerate(is_non_silent):
        if active and start_idx is None:
            start_idx = i
        elif not active and start_idx is not None:
            segments.append((start_idx * time_per_window, i * time_per_window))
            start_idx = None
    if start_idx is not None:
        segments.append((start_idx * time_per_window, len(is_non_silent) * time_per_window))
    return segments


def _transcribe_to_ass(
    input_path: str,
    output_ass_path: str,
    language: str,
    model_size: str,
) -> None:
    import re
    from faster_whisper import WhisperModel

    lang = language if language != "auto" else None
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_iter, _ = model.transcribe(input_path, word_timestamps=True, language=lang)

    result_segments = []
    for seg in segments_iter:
        word_list = [
            {"word": w.word.strip(), "start": w.start, "end": w.end}
            for w in (seg.words or [])
        ]
        result_segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "words": word_list,
        })

    subtitle_size = 96
    primary_color = "&H0000FF00"
    secondary_color = "&H00FFFFFF"
    outline_color = "&H00000000"
    back_color = "&H00000000"

    ass_content = f"""[Script Info]
Title: Auto Karaoke Subtitles
PlayResX: 1080
PlayResY: 1920
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{subtitle_size},{primary_color},{secondary_color},{outline_color},{back_color},1,0,0,0,100,100,0,0,1,14,14,10,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def ms_to_ass_time(ms: int) -> str:
        h = ms // 3600000; ms %= 3600000
        m = ms // 60000; ms %= 60000
        s = ms // 1000; cs = (ms % 1000) // 10
        return f"{h}:{m:02d}:{s:02d}:{cs:02d}"

    def build_tagged(wlist: list) -> str:
        parts = []
        for w in wlist:
            dur_cs = int((w["end"] - w["start"]) * 100)
            word = w["word"].strip()
            if word and dur_cs > 0:
                parts.append("{\\k" + str(dur_cs) + "}" + word)
        return " ".join(parts)

    max_chars = 35

    for segment in result_segments:
        start_ms = int(segment["start"] * 1000)
        end_ms = int(segment["end"] * 1000)
        words = segment.get("words", [])

        if not words:
            t0 = ms_to_ass_time(start_ms)
            t1 = ms_to_ass_time(end_ms)
            ass_content += f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{segment['text']}\n"
            continue

        full_tagged = build_tagged(words)
        clean_text = re.sub(r"\{\\k\d+\}", "", full_tagged).strip()

        if len(clean_text) <= max_chars:
            t0 = ms_to_ass_time(start_ms)
            t1 = ms_to_ass_time(end_ms)
            ass_content += f"Dialogue: 0,{t0},{t1},Default,,0,0,0,,{full_tagged}\n"
        else:
            sub_groups: list = []
            current_group: list = []
            current_length = 0
            current_start = segment["start"]
            for word_info in words:
                word = word_info["word"].strip()
                word_length = len(word) + 1
                if current_length + word_length > max_chars and current_group:
                    sub_groups.append({"words": current_group[:], "start": current_start, "end": word_info["start"]})
                    current_group = [word_info]
                    current_length = word_length
                    current_start = word_info["start"]
                else:
                    current_group.append(word_info)
                    current_length += word_length
            if current_group:
                last_end = current_group[-1]["end"]
                sub_groups.append({"words": current_group, "start": current_start, "end": last_end})

            for group in sub_groups:
                if not group["words"]:
                    continue
                g_start = ms_to_ass_time(int(group["start"] * 1000))
                g_end = ms_to_ass_time(int(group["end"] * 1000))
                group_tagged = build_tagged(group["words"])
                if group_tagged:
                    ass_content += f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{group_tagged}\n"

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)


def _burn_subtitles(
    video_path: str,
    ass_path: str,
    output_path: str,
    subtitle_size: int = 96,
) -> None:
    import os
    import subprocess

    abs_ass = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
    force_style = (
        f"Alignment=10,Fontsize={subtitle_size},"
        "MarginL=0,MarginR=0,MarginV=0,"
        "Outline=8,Shadow=14,BackColour=&H80000000&"
    )
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles='{abs_ass}':force_style='{force_style}'",
        "-vcodec", "h264",
        "-acodec", "aac",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _ass_to_plain_text(ass_content: str) -> str:
    import re
    lines = []
    for line in ass_content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = parts[9].strip()
        text = re.sub(r"\{[^}]*\}", "", text)
        if text:
            lines.append(text)
    return "\n".join(lines)
