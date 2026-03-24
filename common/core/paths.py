from __future__ import annotations
import os
from pathlib import Path


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _xdg_cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


def get_common_config_path() -> Path:
    """common/config.yaml"""
    return Path(__file__).parent.parent / "config.yaml"


def get_llm_config_path() -> Path:
    """common/llm/config.yaml"""
    return Path(__file__).parent.parent / "llm" / "config.yaml"


def get_aliases_path() -> Path:
    """~/.config/fast-market/aliases.yaml"""
    p = _xdg_config_home() / "fast-market" / "aliases.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_config_path(tool_name: str) -> Path:
    """~/.config/fast-market/{tool}/config.yaml"""
    p = _xdg_config_home() / "fast-market" / tool_name / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_prompts_dir() -> Path:
    """~/.local/share/fast-market/prompts/"""
    p = _xdg_data_home() / "fast-market" / "prompts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_skills_dir() -> Path:
    """~/.local/share/fast-market/skills/"""
    p = _xdg_data_home() / "fast-market" / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_data_dir() -> Path:
    """~/.local/share/fast-market/data/"""
    p = _xdg_data_home() / "fast-market" / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_cache_dir() -> Path:
    """~/.cache/fast-market/"""
    p = _xdg_cache_home() / "fast-market"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_data_dir(tool_name: str) -> Path:
    """~/.local/share/fast-market/{tool}/"""
    p = _xdg_data_home() / "fast-market" / tool_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_cache_dir(tool_name: str) -> Path:
    """~/.cache/fast-market/{tool}/"""
    p = _xdg_cache_home() / "fast-market" / tool_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_config(tool_name: str) -> Path:
    """~/.config/fast-market/{tool}/config.yaml"""
    return get_tool_config_path(tool_name)


def get_fastmarket_dir() -> Path:
    """~/.local/share/fast-market/"""
    return get_data_dir()
