from __future__ import annotations

import os
from pathlib import Path


def get_fastmarket_dir() -> Path:
    """Return the base directory for all fast-market data."""
    raw_data_home = os.environ.get("XDG_DATA_HOME")
    data_home = (
        Path(raw_data_home).expanduser()
        if raw_data_home
        else (Path.home() / ".local" / "share")
    )
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
    raw_cache_home = os.environ.get("XDG_CACHE_HOME")
    cache_home = (
        Path(raw_cache_home).expanduser()
        if raw_cache_home
        else (Path.home() / ".cache")
    )
    path = cache_home / "fast-market" / tool_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_prompt_aliases_path() -> Path:
    """Return path to prompt-agent aliases config file."""
    raw_config_home = os.environ.get("XDG_CONFIG_HOME")
    config_home = (
        Path(raw_config_home).expanduser()
        if raw_config_home
        else (Path.home() / ".config")
    )
    path = config_home / "prompt-agent" / "aliases.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
