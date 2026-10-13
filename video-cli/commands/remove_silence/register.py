from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

import click

from commands.base import CommandManifest
from commands.remove_silence.transcript import (
    DEFAULT_CROSSFADE,
    DEFAULT_PARAGRAPH_THRESHOLD,
    DEFAULT_PAUSE_COMMA,
    DEFAULT_PAUSE_INLINE,
    DEFAULT_PAUSE_PARAGRAPH,
    DEFAULT_PAUSE_SENTENCE,
    DEFAULT_TOLERANCE,
)


class SilentVideoError(RuntimeError):
    """Raised when a video has no detectable audio (silent mic)."""
    def __init__(self, path: str):
        super().__init__(f"Silent video — no non-silent segments detected: {path}")
        self.path = path


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
    """
    import numpy as np
    from moviepy import concatenate_videoclips

    from commands.media_open import open_video_clip

    video = open_video_clip(input_file)
    original_duration = video.duration
    audio_array = video.audio.to_soundarray(fps=video.audio.fps)
    if len(audio_array.shape) > 1:
        audio_array = np.mean(audio_array, axis=1).astype(np.float32)

    segments = detect_silence_segments_simple(audio_array, video.audio.fps, threshold)

    if not segments:
        video.close()
        raise SilentVideoError(input_file)

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

    video.close()
    final_video.close()
    for clip in clips:
        clip.close()

    return output_file, original_duration, final_duration


# ── Transcript-aware silence removal (local only) ────────────────────────────

def format_dry_run_table(reports: list[dict]) -> str:
    """Render one table row per detected silence for --dry-run."""
    lines = [
        f"{'start':>9} {'end':>9} {'orig(s)':>8} {'type':<11} {'kept(s)':>8}  prev -> next",
        "-" * 78,
    ]
    for rep in reports:
        prev = (rep["prev"][:22] + "…") if len(rep["prev"]) > 23 else rep["prev"]
        nxt = (rep["next"][:22] + "…") if len(rep["next"]) > 23 else rep["next"]
        lines.append(
            f"{rep['start']:9.3f} {rep['end']:9.3f} {rep['original']:8.3f} "
            f"{rep['type']:<11} {rep['kept']:8.3f}  {prev!r} -> {nxt!r}"
        )
    return "\n".join(lines)


def plan_transcript_cuts(
    input_file: str,
    threshold: float,
    transcript_path: str,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    paragraph_threshold: float = DEFAULT_PARAGRAPH_THRESHOLD,
    pause_inline: float = DEFAULT_PAUSE_INLINE,
    pause_comma: float = DEFAULT_PAUSE_COMMA,
    pause_sentence: float = DEFAULT_PAUSE_SENTENCE,
    pause_paragraph: float = DEFAULT_PAUSE_PARAGRAPH,
) -> tuple[float, list[Tuple[float, float]], list[dict]]:
    """Detect silences on the original file and plan transcript-aware keeps.

    Returns (original_duration, keep_intervals, silence_reports).
    Raises SilentVideoError when no non-silent audio is detected.
    """
    import numpy as np

    from commands.media_open import open_video_clip
    from commands.remove_silence.transcript import build_keep_segments, load_transcript

    video = open_video_clip(input_file)
    try:
        original_duration = video.duration
        audio_fps = video.audio.fps
        audio_array = video.audio.to_soundarray(fps=audio_fps)
    finally:
        video.close()
    if len(audio_array.shape) > 1:
        audio_array = np.mean(audio_array, axis=1).astype(np.float32)

    segments = detect_silence_segments_simple(audio_array, audio_fps, threshold)
    if not segments:
        raise SilentVideoError(input_file)

    words = load_transcript(transcript_path)
    keeps, reports = build_keep_segments(
        segments, original_duration, words,
        tolerance=tolerance,
        paragraph_threshold=paragraph_threshold,
        pause_inline=pause_inline,
        pause_comma=pause_comma,
        pause_sentence=pause_sentence,
        pause_paragraph=pause_paragraph,
    )
    return original_duration, keeps, reports


def remove_silence_transcript(
    input_file: str,
    output_file: str,
    threshold: float,
    transcript_path: str,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    paragraph_threshold: float = DEFAULT_PARAGRAPH_THRESHOLD,
    pause_inline: float = DEFAULT_PAUSE_INLINE,
    pause_comma: float = DEFAULT_PAUSE_COMMA,
    pause_sentence: float = DEFAULT_PAUSE_SENTENCE,
    pause_paragraph: float = DEFAULT_PAUSE_PARAGRAPH,
    crossfade: float = DEFAULT_CROSSFADE,
    progress_cb=None,
) -> tuple[str, float, float]:
    """
    Remove silence but keep natural speech pauses, guided by a timestamped
    transcript (word-level JSON preferred, segment-level JSON/SRT otherwise).

    Silence detection is identical to remove_silence_simple; only the
    segments kept differ. A short symmetric audio fade (crossfade) is
    applied at each cut to avoid clicks. Video and audio stay in sync
    because both are cut from the same clip intervals.
    Returns (output_file, original_duration, final_duration).
    """
    import numpy as np
    from moviepy import afx, concatenate_videoclips

    from commands.media_open import open_video_clip
    from commands.remove_silence.transcript import build_keep_segments, load_transcript

    video = open_video_clip(input_file)
    original_duration = video.duration
    audio_array = video.audio.to_soundarray(fps=video.audio.fps)
    if len(audio_array.shape) > 1:
        audio_array = np.mean(audio_array, axis=1).astype(np.float32)

    segments = detect_silence_segments_simple(audio_array, video.audio.fps, threshold)

    if not segments:
        video.close()
        raise SilentVideoError(input_file)

    words = load_transcript(transcript_path)
    keeps, _ = build_keep_segments(
        segments, original_duration, words,
        tolerance=tolerance,
        paragraph_threshold=paragraph_threshold,
        pause_inline=pause_inline,
        pause_comma=pause_comma,
        pause_sentence=pause_sentence,
        pause_paragraph=pause_paragraph,
    )

    clips = []
    for start, end in keeps:
        clip = video.subclipped(start, end)
        if clip.audio is not None and crossfade > 0 and clip.duration:
            fade = min(crossfade, clip.duration / 2)
            if fade > 0:
                clip = clip.with_audio(
                    clip.audio.with_effects([afx.AudioFadeIn(fade), afx.AudioFadeOut(fade)])
                )
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

    video.close()
    final_video.close()
    for clip in clips:
        clip.close()

    return output_file, original_duration, final_duration


# ── CLI ───────────────────────────────────────────────────────────────────────

def _reset_config_callback(ctx, param, value):
    if not value:
        return
    from commands.remove_silence.config import reset_rhythm_config
    path = reset_rhythm_config()
    click.echo(f"Rhythm config reset to defaults: {path}")
    ctx.exit()


def _format_effective_params(params: dict, source: str) -> str:
    threshold = params["paragraph_threshold"]
    paragraph = "infinite" if threshold <= 0 else f"{threshold:.2f}s"
    return (
        "Rhythm params "
        f"(tolerance={params['transcript_tolerance']:.2f}s "
        f"paragraph>{paragraph} "
        f"inline={params['pause_inline']:.2f}s "
        f"comma={params['pause_comma']:.2f}s "
        f"sentence={params['pause_sentence']:.2f}s "
        f"paragraph={params['pause_paragraph']:.2f}s "
        f"crossfade={params['crossfade']*1000:.0f}ms) [{source}]"
    )


def _effective_params_and_source(cli_values: dict) -> tuple[dict, str]:
    """Resolve CLI > config file > defaults; returns (params, source label)."""
    from commands.remove_silence.config import config_file_path, resolve_rhythm_params
    params = resolve_rhythm_params(cli_values)
    path = config_file_path()
    source = f"config: {path}" if path.exists() else "defaults (no config file)"
    if any(v is not None for v in cli_values.values()):
        source += ", CLI overrides applied"
    return params, source

def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("remove-silence")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
    @click.option(
        "--threshold", "-t",
        default=-65.0, show_default=True,
        help="Silence threshold in dB",
    )
    @click.option("--modal/--local", default=False, show_default=True, help="Run this step on Modal instead of locally.")
    @click.option(
        "--use-transcript", type=click.Path(exists=True), default=None,
        help="Timestamped transcript (word-level JSON preferred, else JSON/SRT segments): "
             "keep natural speech pauses instead of removing every silence.",
    )
    @click.option("--transcript-tolerance", type=float, default=None,
                  help="Max gap (s) between a word end and a silence start for alignment "
                       f"(default: {DEFAULT_TOLERANCE}, or remove_silence.transcript_tolerance in config).")
    @click.option("--paragraph-threshold", type=float, default=None,
                  help="Silence (s) after a sentence end that counts as a paragraph pause; "
                       f"0 means infinite, i.e. never (default: {DEFAULT_PARAGRAPH_THRESHOLD:g}, "
                       "or remove_silence.paragraph_threshold in config).")
    @click.option("--pause-inline", type=float, default=None,
                  help="Seconds kept for mid-sentence hesitations "
                       f"(default: {DEFAULT_PAUSE_INLINE}, or remove_silence.pause_inline in config).")
    @click.option("--pause-comma", type=float, default=None,
                  help="Seconds kept after a comma "
                       f"(default: {DEFAULT_PAUSE_COMMA}, or remove_silence.pause_comma in config).")
    @click.option("--pause-sentence", type=float, default=None,
                  help="Seconds kept after a sentence end "
                       f"(default: {DEFAULT_PAUSE_SENTENCE}, or remove_silence.pause_sentence in config).")
    @click.option("--pause-paragraph", type=float, default=None,
                  help="Seconds kept after a paragraph end "
                       f"(default: {DEFAULT_PAUSE_PARAGRAPH}, or remove_silence.pause_paragraph in config).")
    @click.option("--crossfade", type=float, default=None,
                  help="Short audio fade (s) at each cut to avoid clicks (transcript mode only) "
                       f"(default: {DEFAULT_CROSSFADE}, or remove_silence.crossfade in config).")
    @click.option("--dry-run", is_flag=True, default=False,
                  help="Detect silences and print the pause table without writing any file.")
    @click.option("--reset-config", is_flag=True, default=False, is_eager=True,
                  expose_value=False, callback=_reset_config_callback,
                  help="Reset the rhythm-silence section of the video config file to defaults and exit.")
    def remove_silence_cmd(
        input_file: str, output: str | None, threshold: float, modal: bool,
        use_transcript: str | None, transcript_tolerance: float | None,
        paragraph_threshold: float | None, pause_inline: float | None, pause_comma: float | None,
        pause_sentence: float | None, pause_paragraph: float | None, crossfade: float | None,
        dry_run: bool,
    ):
        """Remove silence from a video (RMS-based, exact YouTools algorithm).

        Without --use-transcript every detected silence is removed. With
        --use-transcript, punctuation pauses from the transcript are
        shortened to a natural duration instead.
        """
        input_path = Path(input_file).resolve()
        output_path = (
            Path(output).resolve() if output
            else input_path.parent / f"{input_path.stem}_nosilence{input_path.suffix}"
        )

        if modal and (use_transcript or dry_run):
            raise click.ClickException(
                "--use-transcript/--dry-run is local-only; drop --modal to use it."
            )
        if dry_run and not use_transcript:
            raise click.ClickException("--dry-run requires --use-transcript.")

        click.echo(f"Removing silence from {input_path.name}...", err=True)
        if use_transcript:
            rhythm, source = _effective_params_and_source({
                "transcript_tolerance": transcript_tolerance,
                "paragraph_threshold": paragraph_threshold,
                "pause_inline": pause_inline,
                "pause_comma": pause_comma,
                "pause_sentence": pause_sentence,
                "pause_paragraph": pause_paragraph,
                "crossfade": crossfade,
            })
            click.echo(_format_effective_params(rhythm, source), err=True)
            try:
                if dry_run:
                    _, _, reports = plan_transcript_cuts(
                        str(input_path), threshold, use_transcript,
                        tolerance=rhythm["transcript_tolerance"],
                        paragraph_threshold=rhythm["paragraph_threshold"],
                        pause_inline=rhythm["pause_inline"],
                        pause_comma=rhythm["pause_comma"],
                        pause_sentence=rhythm["pause_sentence"],
                        pause_paragraph=rhythm["pause_paragraph"],
                    )
                    click.echo(format_dry_run_table(reports))
                    return
                _, orig_dur, final_dur = remove_silence_transcript(
                    str(input_path), str(output_path), threshold, use_transcript,
                    tolerance=rhythm["transcript_tolerance"],
                    paragraph_threshold=rhythm["paragraph_threshold"],
                    pause_inline=rhythm["pause_inline"],
                    pause_comma=rhythm["pause_comma"],
                    pause_sentence=rhythm["pause_sentence"],
                    pause_paragraph=rhythm["pause_paragraph"],
                    crossfade=rhythm["crossfade"],
                    progress_cb=None,
                )
            except SilentVideoError as exc:
                raise click.ClickException(str(exc)) from exc
            if orig_dur and final_dur:
                reduction = (orig_dur - final_dur) / orig_dur * 100
                click.echo(
                    f"Duration: {orig_dur:.1f}s → {final_dur:.1f}s ({reduction:.1f}% removed)",
                    err=True,
                )
            click.echo(str(output_path))
            return
        if modal:
            from commands.remote import run_remote_remove_silence
            result = run_remote_remove_silence(input_path, output_path, threshold)
            orig_dur = result.get("original_duration") or 0
            final_dur = result.get("final_duration") or 0
        else:
            try:
                _, orig_dur, final_dur = remove_silence_simple(
                    str(input_path), str(output_path), threshold, progress_cb=None
                )
            except SilentVideoError as exc:
                raise click.ClickException(str(exc)) from exc
        if orig_dur and final_dur:
            reduction = (orig_dur - final_dur) / orig_dur * 100
            click.echo(
                f"Duration: {orig_dur:.1f}s → {final_dur:.1f}s ({reduction:.1f}% removed)",
                err=True,
            )
        click.echo(str(output_path))

    return CommandManifest(name="remove-silence", click_command=remove_silence_cmd)
