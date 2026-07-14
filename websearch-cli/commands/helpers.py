from __future__ import annotations

from pathlib import Path

from common.cli.helpers import out
from common.core.registry import build_plugins

_TOOL_ROOT = Path(__file__).resolve().parents[1]


def build_providers(config: dict, tool_root: Path = _TOOL_ROOT) -> dict:
    """Instantiate all discovered search-provider plugins from config."""
    return build_plugins(config, tool_root=tool_root)
