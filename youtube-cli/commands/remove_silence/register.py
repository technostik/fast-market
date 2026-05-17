from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

import click

from commands.base import CommandManifest


# ── Exact port of detect_silence_segments_simple from YouTools/plugins/trimsilences.py ──

def detect_silence_segments_simple(
    audio_array,
    sample_rate: int,
    threshold_db: float,
) -> List[Tuple[float, float]]:
    import numpy as np
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
    progress_cb=None,
) -> tuple[str, float, float]:
    """
    Remove silence from a video — direct port of TrimsilencesPlugin.remove_silence_simple.
    Returns (output_file, original_duration, final_duration).
    Raises RuntimeError on failure.
    If progress_cb is provided it will be called with (current_pct, total_pct).
    """
    import subprocess
    import numpy as np
    from moviepy import VideoFileClip

    video = VideoFileClip(input_file)
    original_duration = video.duration
    audio_array = video.audio.to_soundarray(fps=video.audio.fps)
    if len(audio_array.shape) > 1:
        audio_array = np.mean(audio_array, axis=1).astype(np.float32)

    segments = detect_silence_segments_simple(audio_array, video.audio.fps, threshold)
    video.close()

    if not segments:
        raise RuntimeError("No non-silent segments detected — check threshold")

    final_duration = sum(end - start for start, end in segments)

    if final_duration >= original_duration:
        raise RuntimeError(
            f"Output video ({final_duration:.1f}s) is not shorter than input ({original_duration:.1f}s) — "
            "no silence was removed; try lowering the threshold"
        )

    # Write ffmpeg concat list and encode with progress tracking
    abs_input = os.path.abspath(input_file).replace("'", "\\'")
    concat_path = os.path.join(os.path.dirname(os.path.abspath(output_file)), "_concat_list.txt")
    with open(concat_path, "w") as f:
        for start, end in segments:
            f.write(f"file '{abs_input}'\n")
            f.write(f"inpoint {start}\n")
            f.write(f"outpoint {end}\n")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_path,
            "-c:v", "libx264", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k",
            "-progress", "pipe:1", "-nostats",
            output_file,
        ]

        if progress_cb is None:
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg failed: {result.stderr.decode(errors='replace')}")
        else:
            last_pct = [0.0]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        cur_sec = us / 1_000_000
                        pct = min(100.0, cur_sec / final_duration * 100)
                        if abs(pct - last_pct[0]) >= 1:
                            last_pct[0] = pct
                            progress_cb(pct, 100)
                    except Exception:
                        pass
            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(f"ffmpeg failed with code {rc}")
    finally:
        if os.path.exists(concat_path):
            os.unlink(concat_path)

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
            str(input_path), str(output_path), threshold, progress_cb=None
        )
        reduction = (orig_dur - final_dur) / orig_dur * 100
        click.echo(
            f"Duration: {orig_dur:.1f}s → {final_dur:.1f}s ({reduction:.1f}% removed)",
            err=True,
        )
        click.echo(str(output_path))

    return CommandManifest(name="remove-silence", click_command=remove_silence_cmd)
