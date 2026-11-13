from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.cut.register import parse_timestamp

LAYOUTS = ("stack", "crop", "fit-blur")

# Fixed portrait canvas for the fit-blur composition.
FIT_BLUR_SIZE = (1080, 1920)
DEFAULT_FG_ZOOM = 1.3
DEFAULT_BG_BLUR = 30.0
DEFAULT_BG_BRIGHTNESS = 0.75


def _even(value: int) -> int:
    """Round down to an even value; H.264 needs even dimensions."""
    return value - value % 2


def _crop_offset(length: int, window: int, center: float) -> int:
    """Start of a ``window``-wide crop inside ``length`` pixels.

    Matches the source plugin: ``0`` anchors the window at the left/top edge,
    ``1`` moves it halfway across the slack, ``-1`` mirrors it. The result is
    clamped so the crop always stays inside the frame.
    """
    if window >= length:
        return 0
    offset = int(center * (length - window) / 2)
    return max(0, min(length - window, offset))


def _portrait_clip(subclip, layout: str, zoom: float, center_x: float, center_y: float):
    """Turn a 16:9 subclip into a 9:16 clip.

    ``stack`` crops the left and right edges of the frame and stacks them
    vertically, keeping the whole image. ``crop`` zooms around
    (``center_x``, ``center_y``) and center-crops to 9:16, keeping the subject.
    """
    from moviepy import CompositeVideoClip

    w, h = subclip.size

    if layout == "stack":
        # Left/right crops are 9:8; two stacked give the 9:16 portrait frame.
        target_w = _even(h)
        if target_w < 2:
            raise ValueError(f"Source frame is too small ({w}x{h}) for a 9:16 layout")
        crop_w = int(h * 9 / 8)
        left = subclip.cropped(x1=0, y1=0, x2=min(crop_w, w), y2=h)
        right = subclip.cropped(x1=max(0, w - crop_w), y1=0, x2=w, y2=h)
        left = left.resized(width=target_w).without_audio()
        right = right.resized(width=target_w).without_audio()
        block_h = left.h
        return CompositeVideoClip(
            [left.with_position((0, 0)), right.with_position((0, block_h))],
            size=(target_w, 2 * block_h),
        ).with_audio(subclip.audio)

    base = subclip
    if zoom != 1.0:
        zoom_w = int(w / zoom)
        zoom_h = int(h / zoom)
        x1 = _crop_offset(w, zoom_w, center_x)
        y1 = _crop_offset(h, zoom_h, center_y)
        base = subclip.cropped(x1=x1, y1=y1, x2=x1 + zoom_w, y2=y1 + zoom_h)
        w, h = base.size

    target_h = _even(h)
    target_w = _even(int(target_h * 9 / 16))
    if target_w < 2 or target_h < 2 or target_w > w:
        raise ValueError(
            f"Cannot produce a 9:16 crop from a {w}x{h} frame with layout 'crop'; "
            "use layout 'stack' for non-landscape sources"
        )
    crop_x = int((w - target_w) / 2)
    return base.cropped(x1=crop_x, y1=0, x2=crop_x + target_w, y2=target_h)


def _clamp_to_duration(
    input_file: str, start_seconds: float, end_seconds: float
) -> float:
    """Reject a start past the end and clamp an end past the last frame."""
    from commands.media_open import container_duration_seconds, packet_span_seconds

    duration = container_duration_seconds(input_file)
    if duration is None:
        duration = packet_span_seconds(input_file)
    if duration is None:
        return end_seconds

    if start_seconds >= duration:
        raise ValueError(
            f"start ({start_seconds:.3f}s) is past the end of {input_file} "
            f"({duration:.3f}s)"
        )
    if end_seconds > duration:
        print(
            f"End ({end_seconds:.3f}s) is past the end of {input_file} "
            f"({duration:.3f}s); clamping.",
            file=sys.stderr,
        )
        return duration
    return end_seconds


def _build_fit_blur_filter(
    foreground_width: int, background_blur: float, background_brightness: float
) -> str:
    """ffmpeg filter graph: blurred cover background + fitted foreground.

    The background fills the 1080x1920 canvas (cover), is blurred and dimmed;
    the foreground is scaled to ``foreground_width`` and centered on top.
    """
    width, height = FIT_BLUR_SIZE
    return (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={background_blur:g},"
        "colorchannelmixer="
        f"rr={background_brightness:g}:gg={background_brightness:g}:"
        f"bb={background_brightness:g}[bgv];"
        f"[fg]scale={foreground_width}:-2[fgv];"
        "[bgv][fgv]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]"
    )


def _fit_blur(
    input_file: str,
    output_file: str,
    start_seconds: float,
    end_seconds: float,
    foreground_zoom: float,
    background_blur: float,
    background_brightness: float,
) -> str:
    """Render the fit+blurred-background layout with ffmpeg."""
    foreground_width = max(2, round(FIT_BLUR_SIZE[0] * foreground_zoom))
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_seconds:.3f}",
        "-i", input_file,
        "-t", f"{end_seconds - start_seconds:.3f}",
        "-filter_complex",
        _build_fit_blur_filter(foreground_width, background_blur, background_brightness),
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        output_file,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg fit-blur conversion failed (exit {result.returncode}):\n"
            f"{result.stderr.strip()}"
        )
    return output_file


def extract_short(
    input_file: str,
    output_file: str,
    start_seconds: float,
    end_seconds: float,
    layout: str = "stack",
    zoom: float = 1.0,
    center_x: float = 0.0,
    center_y: float = 0.0,
    foreground_zoom: float = DEFAULT_FG_ZOOM,
    background_blur: float = DEFAULT_BG_BLUR,
    background_brightness: float = DEFAULT_BG_BRIGHTNESS,
) -> str:
    """Extract ``[start, end]`` from ``input_file`` and convert it to 9:16.

    The source is re-encoded to H.264/AAC. An end past the last frame is
    clamped to the source duration with a warning on stderr.
    """
    from commands.media_open import open_video_clip

    if layout not in LAYOUTS:
        raise ValueError(f"Unknown layout {layout!r}; expected one of {LAYOUTS}")
    if zoom < 1.0:
        raise ValueError(f"zoom must be >= 1.0, got {zoom}")
    if start_seconds < 0:
        raise ValueError(f"start must be >= 0, got {start_seconds}")
    if end_seconds <= start_seconds:
        raise ValueError(
            f"end ({end_seconds:.3f}s) must be after start ({start_seconds:.3f}s)"
        )
    if layout == "fit-blur":
        if foreground_zoom <= 0:
            raise ValueError(f"foreground_zoom must be > 0, got {foreground_zoom}")
        if not 0 <= background_blur <= 1024:
            raise ValueError(
                f"background_blur must be between 0 and 1024, got {background_blur}"
            )
        if not 0 < background_brightness <= 2:
            raise ValueError(
                "background_brightness must be between 0 (exclusive) and 2, "
                f"got {background_brightness}"
            )
    elif layout != "crop" and (zoom != 1.0 or center_x or center_y):
        raise ValueError(
            "zoom/center_x/center_y only apply to layout 'crop'"
        )

    end_seconds = _clamp_to_duration(input_file, start_seconds, end_seconds)

    if layout == "fit-blur":
        return _fit_blur(
            input_file,
            output_file,
            start_seconds,
            end_seconds,
            foreground_zoom,
            background_blur,
            background_brightness,
        )

    source = open_video_clip(input_file)
    subclip = None
    clip = None
    try:
        width, height = source.size
        if layout == "stack" and height > width:
            print(
                f"{input_file} is already portrait ({width}x{height}); stacking "
                "will double its height. Use --layout crop to keep 9:16.",
                file=sys.stderr,
            )

        subclip = source.subclipped(start_seconds, end_seconds)
        clip = _portrait_clip(subclip, layout, zoom, center_x, center_y)

        # temp_audiofile placed next to the output to avoid CWD issues
        temp_audio = os.path.join(
            os.path.dirname(os.path.abspath(output_file)), "temp-audio-short.m4a"
        )
        clip.write_videofile(
            str(output_file),
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=temp_audio,
            remove_temp=True,
            audio_bitrate="192k",
            preset="medium",
            logger=None,
        )
    finally:
        if clip is not None:
            clip.close()
        if subclip is not None:
            subclip.close()
        source.close()

    return str(output_file)


def load_segments(segments_file: str) -> list[dict]:
    """Parse a segments JSON file (a list of ``{title?, start, end}``).

    Times accept the same formats as the CLI. Invalid entries fail loudly with
    the offending index.
    """
    path = Path(segments_file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path} must contain a non-empty JSON list of segments")

    segments = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path} segment {index} is not a JSON object")
        start, end = item.get("start"), item.get("end")
        if start is None or end is None:
            raise ValueError(f"{path} segment {index} is missing 'start' or 'end'")
        start_seconds = parse_timestamp(str(start))
        end_seconds = parse_timestamp(str(end))
        if start_seconds is None or end_seconds is None:
            raise ValueError(
                f"{path} segment {index} has unparseable times: {start!r} -> {end!r}"
            )
        title = item.get("title")
        segments.append(
            {
                "title": title if isinstance(title, str) else None,
                "start": start_seconds,
                "end": end_seconds,
            }
        )
    return segments


def _sanitize_title(title: str) -> str:
    """Turn a segment title into a filesystem-safe file stem."""
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip().strip(".")


def _unique_path(directory: Path, stem: str) -> Path:
    """``directory/stem.mp4``, suffixed with ``(n)`` when it already exists."""
    candidate = directory / f"{stem}.mp4"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}).mp4"
        counter += 1
    return candidate


def extract_segments(
    input_file: str,
    segments_file: str,
    output_dir: str | None = None,
    layout: str = "stack",
    zoom: float = 1.0,
    center_x: float = 0.0,
    center_y: float = 0.0,
    foreground_zoom: float = DEFAULT_FG_ZOOM,
    background_blur: float = DEFAULT_BG_BLUR,
    background_brightness: float = DEFAULT_BG_BRIGHTNESS,
) -> list[str]:
    """Extract every segment in ``segments_file`` from ``input_file``.

    Each output is named after its title, or ``<input stem>_short_<n>`` when
    the segment has no title (``n`` counts the untitled segments in file
    order). Outputs go to ``output_dir`` (the input directory by default).
    """
    segments = load_segments(segments_file)
    input_path = Path(input_file).resolve()
    directory = Path(output_dir).expanduser().resolve() if output_dir else input_path.parent
    directory.mkdir(parents=True, exist_ok=True)

    outputs: list[str] = []
    untitled = 0
    for index, segment in enumerate(segments, start=1):
        stem = _sanitize_title(segment["title"] or "")
        if not stem:
            untitled += 1
            stem = f"{input_path.stem}_short_{untitled}"
        output_path = _unique_path(directory, stem)
        print(f"[{index}/{len(segments)}] {output_path.name}", file=sys.stderr)
        outputs.append(
            extract_short(
                str(input_path),
                str(output_path),
                segment["start"],
                segment["end"],
                layout=layout,
                zoom=zoom,
                center_x=center_x,
                center_y=center_y,
                foreground_zoom=foreground_zoom,
                background_blur=background_blur,
                background_brightness=background_brightness,
            )
        )
    return outputs


def _parse_time(value: str, option: str) -> float:
    seconds = parse_timestamp(value)
    if seconds is None:
        raise click.BadParameter(
            f"invalid time {value!r}; use SS, MM:SS, HH:MM:SS, or HH:MM:SS,mmm",
            param_hint=option,
        )
    return seconds


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("short-extractor")
    @click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
    @click.option(
        "--segments", type=click.Path(exists=True, dir_okay=False), default=None,
        help="JSON list of {title?, start, end} segments to extract as separate shorts",
    )
    @click.option(
        "--start", "-s", default=None, metavar="TIME",
        help="Clip start (SS, MM:SS, HH:MM:SS, or HH:MM:SS,mmm); required without --segments",
    )
    @click.option(
        "--end", "-e", default=None, metavar="TIME",
        help="Clip end in the same formats as --start",
    )
    @click.option(
        "--duration", "-d", type=float, default=None,
        help="Clip length in seconds; alternative to --end",
    )
    @click.option(
        "--layout",
        type=click.Choice(LAYOUTS),
        default="stack",
        show_default=True,
        help=(
            "stack: two 16:9 halves stacked into 9:16; "
            "crop: zoom and center-crop into 9:16; "
            "fit-blur: full-frame foreground over a blurred 1080x1920 background"
        ),
    )
    @click.option("--zoom", type=float, default=1.0, show_default=True,
                  help="Zoom factor for --layout crop")
    @click.option("--center-x", type=float, default=0.0, show_default=True,
                  help="Horizontal zoom anchor in [-1, 1] for --layout crop (0 = left edge)")
    @click.option("--center-y", type=float, default=0.0, show_default=True,
                  help="Vertical zoom anchor in [-1, 1] for --layout crop (0 = top edge)")
    @click.option("--fg-zoom", type=float, default=DEFAULT_FG_ZOOM, show_default=True,
                  help="Foreground scale for --layout fit-blur (1.0 = canvas width)")
    @click.option("--bg-blur", type=float, default=DEFAULT_BG_BLUR, show_default=True,
                  help="Gaussian blur sigma in pixels for --layout fit-blur")
    @click.option("--bg-brightness", type=float, default=DEFAULT_BG_BRIGHTNESS,
                  show_default=True,
                  help="Background brightness multiplier for --layout fit-blur (1.0 = unchanged)")
    @click.option("--output", "-o", type=click.Path(), default=None,
                  help="Output file path (single segment only)")
    @click.option("--output-dir", type=click.Path(), default=None,
                  help="Directory for --segments outputs (default: input directory)")
    def short_extractor_cmd(
        input_file: str,
        segments: str | None,
        start: str | None,
        end: str | None,
        duration: float | None,
        layout: str,
        zoom: float,
        center_x: float,
        center_y: float,
        fg_zoom: float,
        bg_blur: float,
        bg_brightness: float,
        output: str | None,
        output_dir: str | None,
    ):
        """Extract a clip from a video and convert it to 9:16 (portrait)."""
        if segments is not None:
            if start is not None or end is not None or duration is not None:
                raise click.UsageError(
                    "--segments cannot be combined with --start/--end/--duration"
                )
            if output is not None:
                raise click.UsageError("--output is not valid with --segments; use --output-dir")
        else:
            if output_dir is not None:
                raise click.UsageError("--output-dir requires --segments")
            if start is None:
                raise click.UsageError("--start is required without --segments")
            if (end is None) == (duration is None):
                raise click.UsageError("pass exactly one of --end or --duration")

        if zoom < 1.0:
            raise click.BadParameter(f"zoom must be >= 1.0, got {zoom}", param_hint="--zoom")
        for name, value in (("--center-x", center_x), ("--center-y", center_y)):
            if not -1.0 <= value <= 1.0:
                raise click.BadParameter(
                    f"{name} must be between -1 and 1, got {value}", param_hint=name
                )
        if fg_zoom <= 0:
            raise click.BadParameter(
                f"fg-zoom must be > 0, got {fg_zoom}", param_hint="--fg-zoom"
            )
        if not 0 <= bg_blur <= 1024:
            raise click.BadParameter(
                f"bg-blur must be between 0 and 1024, got {bg_blur}",
                param_hint="--bg-blur",
            )
        if not 0 < bg_brightness <= 2:
            raise click.BadParameter(
                f"bg-brightness must be between 0 (exclusive) and 2, got {bg_brightness}",
                param_hint="--bg-brightness",
            )

        crop_options = zoom != 1.0 or center_x or center_y
        fit_options = (
            fg_zoom != DEFAULT_FG_ZOOM
            or bg_blur != DEFAULT_BG_BLUR
            or bg_brightness != DEFAULT_BG_BRIGHTNESS
        )
        if layout == "stack" and (crop_options or fit_options):
            raise click.UsageError(
                "--zoom/--center-x/--center-y only apply to --layout crop; "
                "--fg-zoom/--bg-blur/--bg-brightness only apply to --layout fit-blur"
            )
        if layout == "crop" and fit_options:
            raise click.UsageError(
                "--fg-zoom/--bg-blur/--bg-brightness only apply to --layout fit-blur"
            )
        if layout == "fit-blur" and crop_options:
            raise click.UsageError(
                "--zoom/--center-x/--center-y only apply to --layout crop"
            )

        input_path = Path(input_file).resolve()

        if segments is not None:
            click.echo(
                f"Extracting segments from {input_path.name} as 9:16 ({layout})...",
                err=True,
            )
            outputs = extract_segments(
                str(input_path),
                segments,
                output_dir=output_dir,
                layout=layout,
                zoom=zoom,
                center_x=center_x,
                center_y=center_y,
                foreground_zoom=fg_zoom,
                background_blur=bg_blur,
                background_brightness=bg_brightness,
            )
            for path in outputs:
                click.echo(path)
            return

        start_seconds = _parse_time(start, "--start")
        if end is not None:
            end_seconds = _parse_time(end, "--end")
        else:
            if duration is None or duration <= 0:
                raise click.BadParameter(
                    f"duration must be > 0, got {duration}", param_hint="--duration"
                )
            end_seconds = start_seconds + duration

        output_path = (
            Path(output).resolve() if output
            else input_path.parent / f"{input_path.stem}_short.mp4"
        )

        click.echo(
            f"Extracting {start_seconds:.3f}s-{end_seconds:.3f}s from "
            f"{input_path.name} as 9:16 ({layout})...",
            err=True,
        )
        out = extract_short(
            str(input_path),
            str(output_path),
            start_seconds,
            end_seconds,
            layout=layout,
            zoom=zoom,
            center_x=center_x,
            center_y=center_y,
            foreground_zoom=fg_zoom,
            background_blur=bg_blur,
            background_brightness=bg_brightness,
        )
        click.echo(out)

    return CommandManifest(name="short-extractor", click_command=short_extractor_cmd)
