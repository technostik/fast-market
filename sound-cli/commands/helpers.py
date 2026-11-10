from __future__ import annotations

from pathlib import Path

from common.core.registry import build_plugins

_TOOL_ROOT = Path(__file__).resolve().parents[1]


def build_engine(config: dict, tool_root: Path | None = None):
    """Construct engine instances from config and plugins."""
    if tool_root is None:
        tool_root = _TOOL_ROOT
    return build_plugins(config, tool_root=tool_root)


def resolve_music_engine(
    config: dict,
    explicit: str | None,
    available: list[str],
) -> str:
    """Pick the music engine to use.

    Order: ``--engine`` → ``default_music_engine`` → ``default_engine`` (only
    when it is a music engine, so a TTS default like ``kokoro`` is ignored) →
    ``acestep`` → the first available music engine.
    """
    if explicit:
        if explicit not in available:
            raise ValueError(
                f"Unknown music engine '{explicit}'. "
                f"Available: {', '.join(available) or '(none)'}"
            )
        return explicit

    for candidate in (
        config.get("default_music_engine"),
        config.get("default_engine"),
        "acestep",
    ):
        if candidate and candidate in available:
            return candidate

    if not available:
        raise ValueError(
            "No music engines available. Install one with: "
            "pip install 'sound-agent[acestep]'"
        )
    return available[0]
