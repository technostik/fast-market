from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import click

# Dynamic-range compressor defaults, ported as-is from YouTools'
# normalize_full_audio() (used in production by its directpublish plugin).
THRESHOLD_DB = -30
RATIO = 4
ATTACK_MS = 20
RELEASE_MS = 200
MAKEUP_MIN = 1.0
MAKEUP_MAX = 64.0

_MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise click.ClickException("ffmpeg not found on PATH (required for volume analysis/normalization).")


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
