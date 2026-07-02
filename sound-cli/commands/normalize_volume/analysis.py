from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import click

from common.youtube.utils import extract_video_id

# Dynamic-range compressor defaults, ported as-is from YouTools'
# normalize_full_audio() (used in production by its directpublish plugin).
THRESHOLD_DB = -30
RATIO = 4
ATTACK_MS = 20
RELEASE_MS = 200
MAKEUP_MIN = 1.0
MAKEUP_MAX = 64.0

DEFAULT_REFERENCE_CLIP_SECS = 60

# The compressor's makeup gain is computed open-loop from a single before/after
# mean-volume gap (see compute_makeup_gain), but the compressor itself also
# changes the mean volume by an amount that depends on how much of the file's
# content sits above THRESHOLD_DB - which the makeup-gain formula can't predict.
# For files with a wide dynamic range (quiet overall but with loud passages
# above -30dB), the ratio-based attenuation can outweigh the makeup boost
# entirely, landing the result further from the target than the input was.
# CORRECTION_TOLERANCE_DB gates a second, measured corrective pass (see
# residual_correction_gain / apply_flat_gain) that closes that residual gap
# exactly, after the first pass has already done its dynamic-range shaping.
CORRECTION_TOLERANCE_DB = 0.5

_MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise click.ClickException("ffmpeg not found on PATH (required for volume analysis/normalization).")


def is_youtube_url(source: str) -> bool:
    """True if SOURCE looks like a YouTube URL (watch/youtu.be/shorts), not a local path."""
    return extract_video_id(source) is not None


def download_youtube_clip(
    url: str,
    duration_secs: int = DEFAULT_REFERENCE_CLIP_SECS,
    cookies: str | None = None,
) -> Path:
    """Download only the first duration_secs of a YouTube video, for reference-volume analysis.

    Uses yt-dlp's download_ranges (HTTP range requests against YouTube's DASH streams)
    so only the needed portion is fetched - not the whole video - matching the
    yt_dlp.YoutubeDL library pattern already used elsewhere in this repo
    (common/youtube/transport.py, youtube-cli/commands/get_video/register.py).
    Caller is responsible for deleting the returned file's parent directory.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise click.ClickException(
            "yt-dlp not installed. Install with: pip install 'sound-agent[youtube]'"
        ) from exc

    video_id = extract_video_id(url)
    if not video_id:
        raise click.ClickException(f"Not a recognized YouTube URL: {url}")

    out_dir = Path(tempfile.mkdtemp(prefix="sound-normvol-"))
    ydl_opts: dict = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "outtmpl": str(out_dir / f"{video_id}.%(ext)s"),
        "download_ranges": yt_dlp.utils.download_range_func(None, [(0, duration_secs)]),
        "force_keyframes_at_cuts": True,
        "quiet": True,
        "no_warnings": True,
    }
    if cookies:
        ydl_opts["cookiefile"] = cookies

    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([watch_url])
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise click.ClickException(f"YouTube download failed: {e}") from e

    downloaded = list(out_dir.glob(f"{video_id}.*"))
    if not downloaded:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise click.ClickException(f"yt-dlp reported success but no file was found in {out_dir}")
    return downloaded[0]


def measure_mean_volume(path: Path) -> float:
    """Measure the mean volume (dBFS) of an audio or video file via ffmpeg's volumedetect filter."""
    _require_ffmpeg()
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = _MEAN_VOLUME_RE.search(result.stderr)
    if not match:
        raise click.ClickException(
            f"Could not determine mean volume of {path} (ffmpeg volumedetect produced no output)."
        )
    return float(match.group(1))


def compute_makeup_gain(target_dbfs: float, input_dbfs: float) -> float:
    """Linear makeup gain (1-64) for ffmpeg's acompressor, from a target/input dBFS gap.

    Ported from YouTools' normalize_full_audio(), which computed this gap in dB
    and clamped it directly into acompressor's makeup= range - but that parameter
    is a linear multiplier (1-64), not dB. This converts dB -> linear first.
    """
    gain_db = target_dbfs - input_dbfs
    makeup_linear = 10 ** (gain_db / 20)
    return max(MAKEUP_MIN, min(MAKEUP_MAX, makeup_linear))


def apply_dynamic_normalization(
    input_path: Path,
    output_path: Path,
    makeup_gain: float,
    *,
    threshold_db: float = THRESHOLD_DB,
    ratio: float = RATIO,
    attack_ms: float = ATTACK_MS,
    release_ms: float = RELEASE_MS,
) -> None:
    """Apply dynamic-range compression + makeup gain to INPUT's audio, video stream untouched."""
    _require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    compressor = (
        f"acompressor=threshold={threshold_db}dB:ratio={ratio}:"
        f"attack={attack_ms}:release={release_ms}:makeup={makeup_gain}"
    )
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", compressor,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise click.ClickException(f"ffmpeg normalization failed: {result.stderr[-800:]}")


def residual_correction_gain(
    target_dbfs: float, actual_dbfs: float, tolerance_db: float = CORRECTION_TOLERANCE_DB
) -> float | None:
    """Flat dB gain needed to correct actual_dbfs to target_dbfs, or None if
    already within tolerance_db. See CORRECTION_TOLERANCE_DB for why this is
    needed on top of the compressor's open-loop makeup gain."""
    residual = target_dbfs - actual_dbfs
    return residual if abs(residual) > tolerance_db else None


def apply_flat_gain(input_path: Path, output_path: Path, gain_db: float) -> None:
    """Apply a flat linear gain (no compression) to INPUT's audio, video stream untouched.
    Used as a corrective second pass after apply_dynamic_normalization - see
    residual_correction_gain. A positive correction can push already-loud peaks
    close to or past 0 dBFS, so a true-peak limiter (alimiter) caps the output
    just under full scale to avoid clipping/distortion, rather than trusting the
    flat gain alone."""
    _require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            # level=false: alimiter's default "auto level" mode re-optimizes output
            # gain back up toward full scale regardless of `limit`, defeating the
            # point of a headroom ceiling - level=false makes `limit` a hard cap.
            "-af", f"volume={gain_db}dB,alimiter=limit=0.891:level=false",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise click.ClickException(f"ffmpeg gain correction failed: {result.stderr[-800:]}")
