from __future__ import annotations

import os
from pathlib import Path


def get_fastmarket_dir() -> Path:
    """Return the base directory for all fast-market data."""
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "fast-market"


def get_tool_config(tool_name: str) -> Path:
    """Return path to a tool-specific YAML config file."""
    return get_fastmarket_dir() / "config" / f"{tool_name}.yaml"


def get_tool_data_dir(tool_name: str) -> Path:
    """Return and create a tool-specific data directory."""
    path = get_fastmarket_dir() / "data" / tool_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_tool_cache_dir(tool_name: str) -> Path:
    """Return and create a tool-specific cache directory."""
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = cache_home / "fast-market" / tool_name
    path.mkdir(parents=True, exist_ok=True)
    return path

