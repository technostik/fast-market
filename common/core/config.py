from __future__ import annotations

import os
import warnings
from pathlib import Path

import yaml
from common.core.paths import (
    get_common_config_path,
    get_llm_config_path,
    get_youtube_config_path,
    get_youtube_channel_list_path,
    get_tool_config_path,
    get_common_subconfig_path,
    get_agent_config_path,
)
from common.core.yaml_utils import dump_yaml


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


_tool_common_requirements: dict[str, list[str]] = {}


def requires_common_config(tool_name: str, required_subconfigs: list[str]) -> None:
    """Register which common sub-configs a tool requires.

    Call this in your tool's entry point before loading config:
        requires_common_config("task", ["llm"])
        requires_common_config("youtube", ["llm", "youtube"])

    If a required subconfig is missing, load_tool_config() will raise ConfigError.
    """
    _tool_common_requirements[tool_name] = required_subconfigs


def _get_tool_requirements(tool_name: str) -> list[str]:
    """Get required subconfigs for a tool, or empty list if not declared."""
    return _tool_common_requirements.get(tool_name, [])


def _discover_common_subconfigs() -> dict[str, dict]:
    """Discover all common sub-configs by scanning ~/.config/fast-market/common/.

    Returns {subconfig_name: config_dict} for each subdirectory containing config.yaml.
    """
    common_dir = get_common_config_path().parent
    if not common_dir.exists():
        return {}

    subconfigs = {}
    for subdir in common_dir.iterdir():
        if not subdir.is_dir():
            continue
        config_file = subdir / "config.yaml"
        if config_file.exists():
            subconfigs[subdir.name] = _load_yaml(config_file)

    return subconfigs


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively. Override wins on conflict.
    Neither input is mutated. Returns new dict.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    """Load YAML file, return empty dict if doesn't exist."""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a YAML mapping, got {type(data).__name__}")
    return data


def _save_yaml(path: Path, config: dict) -> None:
    """Save config to YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dump_yaml(config, sort_keys=False),
        encoding="utf-8",
    )


def load_common_config() -> dict:
    """Load ~/.config/fast-market/common/config.yaml.

    Returns empty dict if file does not exist.
    """
    return _load_yaml(get_common_config_path())


def save_common_config(config: dict) -> None:
    """Save to ~/.config/fast-market/common/config.yaml."""
    _save_yaml(get_common_config_path(), config)


def is_workdir_locked(workdir_path: str | None = None) -> bool:
    """Check if a workdir is locked via .lock file."""
    if workdir_path is None:
        cfg = load_common_config()
        workdir_path = cfg.get("workdir")
    if not workdir_path:
        return False
    from pathlib import Path
    return (Path(workdir_path) / ".lock").exists()


def add_workdir_lock(workdir_path: str | None = None) -> bool:
    """Add a .lock file to the workdir. Returns True if lock was added."""
    if workdir_path is None:
        cfg = load_common_config()
        workdir_path = cfg.get("workdir")
    if not workdir_path:
        return False
    from pathlib import Path
    workdir = Path(workdir_path)
    if not workdir.exists():
        return False
    lock_path = workdir / ".lock"
    if lock_path.exists():
        return False
    lock_path.touch()
    return True


def remove_workdir_lock(workdir_path: str | None = None) -> bool:
    """Remove the .lock file from the workdir. Returns True if lock was removed."""
    if workdir_path is None:
        cfg = load_common_config()
        workdir_path = cfg.get("workdir")
    if not workdir_path:
        return False
    from pathlib import Path
    lock_path = Path(workdir_path) / ".lock"
    if lock_path.exists():
        lock_path.unlink()
        return True
    return False


def get_lock_wait_timeout() -> int:
    """Get the lock wait timeout in seconds. Default is 600 (10 minutes)."""
    config = load_common_config()
    return config.get("lock_wait_timeout", 600)


# Config keys reference for documentation:
# common/config.yaml keys:
#   workdir: null | str - current workdir path
#   workdir_root: null | str - root directory for workdirs
#   workdir_prefix: str - prefix for new workdirs (default: "work-")
#   previous_workdir: null | str - previous workdir for release command
#   lock_wait_timeout: int - seconds to wait for lock release (default: 600)
#   snapshot_root: null | str - root for backup snapshots


def load_llm_config() -> dict:
    """Load ~/.config/fast-market/common/llm/config.yaml.

    Returns empty dict if file does not exist.
    """
    return _load_yaml(get_llm_config_path())


def save_llm_config(config: dict) -> None:
    """Save to ~/.config/fast-market/common/llm/config.yaml."""
    _save_yaml(get_llm_config_path(), config)


def load_youtube_config() -> dict:
    """Load ~/.config/fast-market/common/youtube/config.yaml.

    Returns empty dict if file does not exist.
    """
    return _load_yaml(get_youtube_config_path())


def save_youtube_config(config: dict) -> None:
    """Save to ~/.config/fast-market/common/youtube/config.yaml."""
    _save_yaml(get_youtube_config_path(), config)


def load_youtube_channel_list_config() -> dict:
    """Load the channel list file path from youtube config.

    Returns dict with 'channel_list_path' and 'default_thematic' keys.
    """
    yt_cfg = load_youtube_config()
    return {
        "channel_list_path": yt_cfg.get(
            "channel_list_path", str(get_youtube_channel_list_path())
        ),
        "default_thematic": yt_cfg.get("default_thematic", ""),
    }


def save_youtube_channel_list_config(
    channel_list_path: str = "", default_thematic: str = ""
) -> None:
    """Save the channel list file path and default thematic to youtube config."""
    yt_cfg = load_youtube_config()
    if channel_list_path:
        yt_cfg["channel_list_path"] = channel_list_path
    if default_thematic:
        yt_cfg["default_thematic"] = default_thematic
    save_youtube_config(yt_cfg)


def load_agent_config() -> dict:
    """Load ~/.config/fast-market/common/agent/config.yaml.

    Returns empty dict if file does not exist.
    This is the shared agent config for skill, task, and prompt CLIs.
    """
    return _load_yaml(get_agent_config_path())


def save_agent_config(config: dict) -> None:
    """Save to ~/.config/fast-market/common/agent/config.yaml."""
    _save_yaml(get_agent_config_path(), config)


def load_tool_config(tool_name: str, path: str | None = None) -> dict:
    """Load effective config for a tool.

    Resolution order (later wins):
    1. Common config (~/.config/fast-market/common/config.yaml) - workdir
    2. Discovered common sub-configs (~/.config/fast-market/common/*/config.yaml)
    3. Tool config (~/.config/fast-market/{tool}/config.yaml)

    Before loading, the tool must declare its common config requirements via
    requires_common_config(). If a required subconfig is missing, ConfigError is raised.

    Sub-configs are discovered by scanning the common/ directory. All discovered
    sub-configs are merged (tool can override specific keys). The tool's config
    can override 'llm.default_provider' only - never providers list.
    """
    required_subconfigs = _get_tool_requirements(tool_name)
    discovered_subconfigs = _discover_common_subconfigs()

    for subconfig in required_subconfigs:
        if subconfig not in discovered_subconfigs:
            raise ConfigError(
                f"Required common config '{subconfig}' not found. Run: toolsetup"
            )

    common_cfg = load_common_config()
    discovered_cfg = {}
    for subconfig_name, subconfig_data in discovered_subconfigs.items():
        discovered_cfg[subconfig_name] = subconfig_data

    if path is not None:
        tool_path = Path(path).expanduser()
    else:
        override_dir = os.environ.get("FASTMARKET_CONFIG_DIR")
        if override_dir:
            tool_path = Path(override_dir).expanduser() / f"{tool_name}.yaml"
        else:
            deprecated_path = Path("config.yaml")
            if deprecated_path.exists():
                warnings.warn(
                    "config.yaml in current directory is deprecated. "
                    f"Move to {get_tool_config_path(tool_name)}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                tool_path = deprecated_path
            else:
                tool_path = get_tool_config_path(tool_name)

    if not tool_path.exists():
        tool_data = {}
    else:
        try:
            tool_data = yaml.safe_load(tool_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {tool_path}: {exc}") from exc

        if tool_data is None:
            tool_data = {}
        elif not isinstance(tool_data, dict):
            raise ConfigError(
                f"{tool_path} must be a YAML mapping, got {type(tool_data).__name__}"
            )

    base = {**common_cfg, **discovered_cfg}
    return _deep_merge(base, tool_data)


def save_tool_config(tool_name: str, config: dict) -> None:
    """Save tool-specific config. Never writes llm.providers (global only)."""
    path = get_tool_config_path(tool_name)
    safe = dict(config)
    if "llm" in safe and "providers" in safe.get("llm", {}):
        safe["llm"] = {k: v for k, v in safe["llm"].items() if k != "providers"}
        if not safe["llm"]:
            del safe["llm"]
    path.write_text(
        dump_yaml(safe, sort_keys=False),
        encoding="utf-8",
    )


def resolve_llm_config(tool_name: str) -> dict:
    """Return the effective LLM config for a tool.

    Returns LLM config dict (providers + default_provider + default_temperature) from either
    top-level keys or the 'llm' section for backward compatibility.
    Raises ConfigError if no llm config found at all.
    """
    cfg = load_tool_config(tool_name)
    if "providers" in cfg:
        default_provider = cfg.get("default_provider", "")
        if not default_provider:
            raise ConfigError("No default LLM provider set. Run: toolsetup")
        return {
            "providers": cfg.get("providers", {}),
            "default_provider": default_provider,
            "default_temperature": cfg.get("default_temperature", 0.3),
        }
    llm = cfg.get("llm", {})
    if not llm:
        raise ConfigError("No LLM configured. Run: toolsetup")
    if not llm.get("default_provider"):
        raise ConfigError("No default LLM provider set. Run: toolsetup")
    return {
        "providers": llm.get("providers", {}),
        "default_provider": llm["default_provider"],
        "default_temperature": llm.get("default_temperature", 0.3),
    }


def _resolve_config_path(tool_name: str, path: str | None = None) -> Path:
    """Resolve config path for a tool."""
    if path is not None:
        return Path(path).expanduser()

    override_dir = os.environ.get("FASTMARKET_CONFIG_DIR")
    if override_dir:
        return Path(override_dir).expanduser() / f"{tool_name}.yaml"

    deprecated_path = Path("config.yaml")
    if deprecated_path.exists():
        warnings.warn(
            "config.yaml in current directory is deprecated. "
            f"Move to {get_tool_config_path(tool_name)}",
            DeprecationWarning,
            stacklevel=2,
        )
        return deprecated_path

    return get_tool_config_path(tool_name)


def load_config(path: str | None = None) -> dict:
    """Load corpus config for backward compatibility."""
    return load_tool_config("corpus", path)


# ─── Smart config splitting for shared youtube config ─────────────────────────

_YOUTUBE_KEYS = {"youtube"}
_GLOBAL_ONLY_KEYS = {"llm"}  # llm.providers is global-only


def _extract_youtube_config(merged: dict) -> dict:
    """Extract only the youtube section from a merged config dict."""
    result = {}
    if "youtube" in merged:
        result["youtube"] = dict(merged["youtube"])
    return result


def _extract_tool_config(merged: dict, tool_name: str) -> dict:
    """Extract tool-specific keys from merged config (exclude shared sections)."""
    result = {}
    for key, value in merged.items():
        if key in _YOUTUBE_KEYS:
            continue
        if key in _GLOBAL_ONLY_KEYS:
            # Only keep tool-specific llm keys (not providers)
            if isinstance(value, dict):
                filtered = {k: v for k, v in value.items() if k != "providers"}
                if filtered:
                    result[key] = filtered
            continue
        result[key] = value
    return result


def split_and_save_config(tool_name: str, config: dict) -> None:
    """Smart save: split config into shared youtube part + tool-specific part.

    The youtube section is saved to common/youtube/config.yaml.
    All other sections are saved to the tool's config file.
    """
    # Save shared youtube config
    yt_cfg = _extract_youtube_config(config)
    if yt_cfg:
        save_youtube_config(yt_cfg["youtube"])

    # Save tool-specific config
    tool_cfg = _extract_tool_config(config, tool_name)
    if tool_cfg:
        save_tool_config(tool_name, tool_cfg)


# Common config schema (~/.config/fast-market/common/config.yaml):
#   workdir: null    # optional global default working directory
#
# LLM config schema (~/.config/fast-market/common/llm/config.yaml):
#   default_provider: anthropic        # required for LLM commands
#   providers:
#     anthropic:
#       model: claude-sonnet-4-20250514
#       api_key_env: ANTHROPIC_API_KEY
#     openai:
#       model: gpt-4
#       api_key_env: OPENAI_API_KEY
#     ollama:
#       model: llama3.2
#       base_url: http://127.0.0.1:11434
#     openai-compatible:
#       model: gpt-4o-mini
#       base_url: https://api.openai.com/v1
#       api_key_env: OPENAI_COMPATIBLE_API_KEY
#
# YouTube config schema (~/.config/fast-market/common/youtube/config.yaml):
#   client_secret_path: ~/.config/fast-market/common/youtube/client_secret.json
#   channel_id: UC...
#   quota_limit: 10000
#
# Tool config schema (~/.config/fast-market/{tool}/config.yaml):
#   llm:
#     default_provider: ollama   # override default for this tool only
#   # tool-specific keys below
