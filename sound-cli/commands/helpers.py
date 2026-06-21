from __future__ import annotations

from pathlib import Path

from common.core.registry import build_plugins

from core.config import load_sound_config

_TOOL_ROOT = Path(__file__).resolve().parents[1]


def build_engine(config: dict, tool_root: Path | None = None):
    """Construct engine instances from config and plugins."""
    if tool_root is None:
        tool_root = _TOOL_ROOT
    return build_plugins(config, tool_root=tool_root)
