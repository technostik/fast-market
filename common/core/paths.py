from __future__ import annotations
import os
from pathlib import Path

from common.core.profile import SHARED, resolve_profile


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _xdg_cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


# ─── Profile-scoped roots ─────────────────────────────────────────────────────
# Every fast-market path lives under ~/.<xdg>/fast-market/profiles/<profile>/.
# Passing profile=None resolves the active profile; pass an explicit name (e.g.
# the SHARED base) to address another profile.


def _profile_config_root(profile: str | None = None) -> Path:
    name = profile or resolve_profile()
    return _xdg_config_home() / "fast-market" / "profiles" / name


def _profile_data_root(profile: str | None = None) -> Path:
    name = profile or resolve_profile()
    return _xdg_data_home() / "fast-market" / "profiles" / name


def _profile_cache_root(profile: str | None = None) -> Path:
    name = profile or resolve_profile()
    return _xdg_cache_home() / "fast-market" / "profiles" / name


def get_profile_config_root(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/ (created)."""
    p = _profile_config_root(profile)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_profile_data_root(profile: str | None = None) -> Path:
    """~/.local/share/fast-market/profiles/<profile>/ (created)."""
    p = _profile_data_root(profile)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_profiles_config_base() -> Path:
    """~/.config/fast-market/profiles/ (not created)."""
    return _xdg_config_home() / "fast-market" / "profiles"


def _xdg_common_config_home(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/"""
    p = _profile_config_root(profile) / "common"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_common_config_path(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/config.yaml"""
    p = _xdg_common_config_home(profile) / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_llm_config_path(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/llm/config.yaml"""
    p = _xdg_common_config_home(profile) / "llm" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_youtube_config_path(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/youtube/config.yaml"""
    p = _xdg_common_config_home(profile) / "youtube" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_youtube_channel_list_path(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/youtube/channels.yaml"""
    p = _xdg_common_config_home(profile) / "youtube" / "channels.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_youtube_auth_dir(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/youtube/ (client_secret + token)."""
    p = _xdg_common_config_home(profile) / "youtube"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_common_subconfig_path(subconfig: str, profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/{subconfig}/config.yaml"""
    p = _xdg_common_config_home(profile) / subconfig / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_aliases_path(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/aliases.yaml"""
    p = _profile_config_root(profile) / "aliases.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_config_path(tool_name: str, profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/{tool}/config.yaml"""
    p = _profile_config_root(profile) / tool_name / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_prompts_dir(profile: str | None = None) -> Path:
    """~/.local/share/fast-market/profiles/<profile>/prompts/ (writable)."""
    p = _profile_data_root(profile) / "prompts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_skills_dir(profile: str | None = None) -> Path:
    """~/.local/share/fast-market/profiles/<profile>/skills/ (writable)."""
    p = _profile_data_root(profile) / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_data_dir(profile: str | None = None) -> Path:
    """~/.local/share/fast-market/profiles/<profile>/data/"""
    p = _profile_data_root(profile) / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_cache_dir(profile: str | None = None) -> Path:
    """~/.cache/fast-market/profiles/<profile>/"""
    p = _profile_cache_root(profile)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_data_dir(tool_name: str, profile: str | None = None) -> Path:
    """~/.local/share/fast-market/profiles/<profile>/{tool}/"""
    p = _profile_data_root(profile) / tool_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_cache_dir(tool_name: str, profile: str | None = None) -> Path:
    """~/.cache/fast-market/profiles/<profile>/{tool}/"""
    p = _profile_cache_root(profile) / tool_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_tool_config(tool_name: str, profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/{tool}/config.yaml"""
    return get_tool_config_path(tool_name, profile)


def get_agent_config_path(profile: str | None = None) -> Path:
    """~/.config/fast-market/profiles/<profile>/common/agent/config.yaml"""
    p = _xdg_common_config_home(profile) / "agent" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_browser_cmds_dir(profile: str | None = None) -> Path:
    """~/.local/share/fast-market/profiles/<profile>/browser-commands/ (writable)."""
    p = _profile_data_root(profile) / "browser-commands"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_browser_user_data_dir(profile: str | None = None) -> Path:
    """~/.cache/fast-market/profiles/<profile>/browser/chrome-profile/ (Chrome session)."""
    p = _profile_cache_root(profile) / "browser" / "chrome-profile"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_fastmarket_dir(profile: str | None = None) -> Path:
    """~/.local/share/fast-market/profiles/<profile>/data/"""
    return get_data_dir(profile)


# ─── Shared-aware search dirs for resource collections ────────────────────────
# Resources (prompts, skills, browser-commands) are file collections: the active
# profile's dir shadows the _shared base. Search order: [profile, _shared]. Only
# existing directories are returned, so a missing _shared base is simply absent.


def _resource_search_dirs(profile_dir: Path, shared_dir: Path) -> list[Path]:
    dirs: list[Path] = [profile_dir]
    if shared_dir != profile_dir and shared_dir.exists():
        dirs.append(shared_dir)
    return dirs


def get_prompts_search_dirs(profile: str | None = None) -> list[Path]:
    """[active prompts dir, _shared prompts dir] — profile shadows shared."""
    active = get_prompts_dir(profile)
    shared = _profile_data_root(SHARED) / "prompts"
    return _resource_search_dirs(active, shared)


def get_skills_search_dirs(profile: str | None = None) -> list[Path]:
    """[active skills dir, _shared skills dir] — profile shadows shared."""
    active = get_skills_dir(profile)
    shared = _profile_data_root(SHARED) / "skills"
    return _resource_search_dirs(active, shared)


def get_browser_cmds_search_dirs(profile: str | None = None) -> list[Path]:
    """[active browser-commands dir, _shared browser-commands dir]."""
    active = get_browser_cmds_dir(profile)
    shared = _profile_data_root(SHARED) / "browser-commands"
    return _resource_search_dirs(active, shared)
