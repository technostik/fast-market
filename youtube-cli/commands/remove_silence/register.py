from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

import click
import numpy as np

from commands.base import CommandManifest


# ── Exact port of detect_silence_segments_simple from YouTools/plugins/trimsilences.py ──

def detect_silence_segments_simple(
    audio_array: np.ndarray,
    sample_rate: int,
    threshold_db: float,
) -> List[Tuple[float, float]]:
    threshold_amp = 10 ** (threshold_db / 20)
    window_size = int(sample_rate / 30)  # Granularité au niveau des frames (env. 33ms)
    if window_size == 0:
        return []
    num_windows = len(audio_array) // window_size
    if num_windows == 0:
        return []
    audio_array = audio_array[:num_windows * window_size]
    rms = np.array([np.sqrt(np.mean(window**2))
                   for window in np.array_split(audio_array, num_windows)])
    is_non_silent = rms >= threshold_amp
    time_per_window = window_size / sample_rate
    segments = []
    start_idx = None
    for i in range(len(is_non_silent)):
        if is_non_silent[i] and start_idx is None:
            start_idx = i
        elif not is_non_silent[i] and start_idx is not None:
            segments.append((start_idx * time_per_window, i * time_per_window))
            start_idx = None
    if start_idx is not None:
        segments.append((start_idx * time_per_window, len(is_non_silent) * time_per_window))
    return segments


# ── Exact port of remove_silence_simple from YouTools/plugins/trimsilences.py ──

def remove_silence_simple(
    input_file: str,
    output_file: str,
    threshold: float,
) -> tuple[str, float, float]:
    """
    Remove silence from a video — direct port of TrimsilencesPlugin.remove_silence_simple.
    Returns (output_file, original_duration, final_duration).
    Raises RuntimeError on failure.
    """
    from moviepy import VideoFileClip, concatenate_videoclips

    video = VideoFileClip(input_file)
    original_duration = video.duration
    audio_array = video.audio.to_soundarray(fps=video.audio.fps)
    if len(audio_array.shape) > 1:
        audio_array = np.mean(audio_array, axis=1).astype(np.float32)

    segments = detect_silence_segments_simple(audio_array, video.audio.fps, threshold)

    if not segments:
        video.close()
        raise RuntimeError("No non-silent segments detected — check threshold")

    clips = []
    for i, (start, end) in enumerate(segments):
        clip = video.subclipped(start, end)
        clips.append(clip)

    final_video = concatenate_videoclips(clips)

    # temp_audiofile placed next to output to avoid CWD issues
    temp_audio = os.path.join(os.path.dirname(os.path.abspath(output_file)), "temp-audio.m4a")
    final_video.write_videofile(
        output_file,
        codec='libx264',
        audio_codec='aac',
        temp_audiofile=temp_audio,
        remove_temp=True,
        audio_bitrate="192k",
        preset='medium',
    )

    final_duration = final_video.duration

    if final_duration >= original_duration:
        video.close()
        final_video.close()
        for clip in clips:
            clip.close()
        if os.path.exists(output_file):
            os.remove(output_file)
        raise RuntimeError(
            f"Output video ({final_duration:.1f}s) is not shorter than input ({original_duration:.1f}s) — "
            "no silence was removed; try lowering the threshold"
        )

    reduction_percentage = ((original_duration - final_duration) / original_duration * 100)

    video.close()
    final_video.close()
    for clip in clips:
        clip.close()

    return output_file, original_duration, final_duration


# ── CLI ───────────────────────────────────────────────────────────────────────

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("remove-silence")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
    @click.option(
        "--threshold", "-t",
        default=-65.0, show_default=True,
        help="Silence threshold in dB",
    )
    def remove_silence_cmd(input_file: str, output: str | None, threshold: float):
        """Remove silence from a video (RMS-based, exact YouTools algorithm)."""
        input_path = Path(input_file).resolve()
        output_path = (
            Path(output).resolve() if output
            else input_path.parent / f"{input_path.stem}_nosilence{input_path.suffix}"
        )

        click.echo(f"Removing silence from {input_path.name}...", err=True)
        _, orig_dur, final_dur = remove_silence_simple(
            str(input_path), str(output_path), threshold
        )
        reduction = (orig_dur - final_dur) / orig_dur * 100
        click.echo(
            f"Duration: {orig_dur:.1f}s → {final_dur:.1f}s ({reduction:.1f}% removed)",
            err=True,
        )
        click.echo(str(output_path))

    return CommandManifest(name="remove-silence", click_command=remove_silence_cmd)
