"""Rhythm-silence configuration: video config file + CLI overrides.

Resolution order: code defaults < config file < CLI options.

The config file is the tool config (``~/.config/fast-market/profiles/<profile>/video/config.yaml``),
section ``remove_silence``:

    remove_silence:
      transcript_tolerance: 0.3
      paragraph_threshold: 0
      pause_inline: 0.1
      pause_comma: 0.25
      pause_sentence: 0.45
      pause_paragraph: 0.9
      crossfade: 0.008
"""

from __future__ import annotations

from pathlib import Path

import click
import yaml

from commands.remove_silence.transcript import (
    DEFAULT_CROSSFADE,
    DEFAULT_PARAGRAPH_THRESHOLD,
    DEFAULT_PAUSE_COMMA,
    DEFAULT_PAUSE_INLINE,
    DEFAULT_PAUSE_PARAGRAPH,
    DEFAULT_PAUSE_SENTENCE,
    DEFAULT_TOLERANCE,
)

CONFIG_SECTION = "remove_silence"

RHYTHM_KEYS = (
    "transcript_tolerance",
    "paragraph_threshold",
    "pause_inline",
    "pause_comma",
    "pause_sentence",
    "pause_paragraph",
    "crossfade",
)

RHYTHM_DEFAULTS: dict[str, float] = {
    "transcript_tolerance": DEFAULT_TOLERANCE,
    "paragraph_threshold": DEFAULT_PARAGRAPH_THRESHOLD,
    "pause_inline": DEFAULT_PAUSE_INLINE,
    "pause_comma": DEFAULT_PAUSE_COMMA,
    "pause_sentence": DEFAULT_PAUSE_SENTENCE,
    "pause_paragraph": DEFAULT_PAUSE_PARAGRAPH,
    "crossfade": DEFAULT_CROSSFADE,
}


def config_file_path() -> Path:
    """Path of the video tool config file (parent dirs created on call)."""
    from common.core.paths import get_tool_config_path

    return get_tool_config_path("video")


def _coerce_number(key: str, value: object, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise click.ClickException(
            f"Invalid {key}={value!r} from {source}: expected a number >= 0."
        )
    result = float(value)
    if result < 0:
        raise click.ClickException(
            f"Invalid {key}={value!r} from {source}: expected a number >= 0."
        )
    return result


def load_rhythm_config() -> dict[str, float]:
    """Effective rhythm params from the config file over the code defaults.

    Missing file or missing section means defaults. Invalid values fail
    loudly with the offending key.
    """
    from common.core.config import ConfigError, load_tool_config

    try:
        cfg = load_tool_config("video")
    except ConfigError as exc:
        raise click.ClickException(
            f"Invalid video config ({config_file_path()}): {exc}\n"
            "Fix it or reset the rhythm section with: "
            "video remove-silence --reset-config"
        ) from exc
    section = cfg.get(CONFIG_SECTION, None)
    if section is None:
        return dict(RHYTHM_DEFAULTS)
    if not isinstance(section, dict):
        raise click.ClickException(
            f"Invalid video config ({config_file_path()}): "
            f"'{CONFIG_SECTION}' must be a mapping."
        )
    params = dict(RHYTHM_DEFAULTS)
    for key in RHYTHM_KEYS:
        if key in section and section[key] is not None:
            params[key] = _coerce_number(key, section[key], "the config file")
    return params


def resolve_rhythm_params(cli_values: dict[str, float | None]) -> dict[str, float]:
    """Merge explicit CLI values (non-None) over the config-file params."""
    params = load_rhythm_config()
    for key in RHYTHM_KEYS:
        value = cli_values.get(key)
        if value is not None:
            params[key] = _coerce_number(key, value, "the command line")
    return params


def reset_rhythm_config() -> Path:
    """Write default rhythm params into the video config file.

    Only the ``remove_silence`` section is touched; other sections are
    preserved. Returns the config file path.
    """
    from common.core.config import save_tool_config

    path = config_file_path()
    if path.exists():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise click.ClickException(f"Invalid YAML in {path}: {exc}") from exc
    else:
        raw = {}
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise click.ClickException(
            f"{path} must be a YAML mapping, got {type(raw).__name__}."
        )
    raw[CONFIG_SECTION] = dict(RHYTHM_DEFAULTS)
    save_tool_config("video", raw)
    return path
