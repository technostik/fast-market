from __future__ import annotations

import os
import warnings
from pathlib import Path

import yaml
from common.core.paths import (
    get_common_config_path,
    get_llm_config_path,
    get_tool_config_path,
)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


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
        yaml.safe_dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def load_common_config() -> dict:
    """Load common/config.yaml.

    Returns empty dict if file does not exist.
    """
    return _load_yaml(get_common_config_path())


def save_common_config(config: dict) -> None:
    """Save to common/config.yaml."""
    _save_yaml(get_common_config_path(), config)


def load_llm_config() -> dict:
    """Load common/llm/config.yaml.

    Returns empty dict if file does not exist.
    """
    return _load_yaml(get_llm_config_path())


def save_llm_config(config: dict) -> None:
    """Save to common/llm/config.yaml."""
    _save_yaml(get_llm_config_path(), config)


def load_tool_config(tool_name: str, path: str | None = None) -> dict:
    """Load effective config for a tool.

    Resolution order (later wins):
    1. Common config (common/config.yaml) - contains workdir
    2. LLM config (common/llm/config.yaml) - contains llm section
    3. Tool config (~/.config/fast-market/{tool}/config.yaml)

    The 'llm' section from LLM config is always the base.
    Tool config can override 'llm.default_provider' only - never providers list.
    Tool-specific keys (not 'llm') are passed through as-is.
    """
    common_cfg = load_common_config()
    llm_cfg = load_llm_config()

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

    base = {**common_cfg, **llm_cfg}
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
        yaml.safe_dump(safe, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def resolve_llm_config(tool_name: str) -> dict:
    """Return the effective LLM config for a tool.

    Returns LLM config dict (providers + default_provider) from either
    top-level keys or the 'llm' section for backward compatibility.
    Raises ConfigError if no llm config found at all.
    """
    cfg = load_tool_config(tool_name)
    if "providers" in cfg:
        default_provider = cfg.get("default_provider", "")
        if not default_provider:
            raise ConfigError("No default LLM provider set. Run: global-setup")
        return {
            "providers": cfg.get("providers", {}),
            "default_provider": default_provider,
        }
    llm = cfg.get("llm", {})
    if not llm:
        raise ConfigError("No LLM configured. Run: global-setup")
    if not llm.get("default_provider"):
        raise ConfigError("No default LLM provider set. Run: global-setup")
    return llm


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


# Common config schema (common/config.yaml):
#   workdir: null    # optional global default working directory
#
# LLM config schema (common/llm/config.yaml):
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
# Tool config schema (~/.config/fast-market/{tool}/config.yaml):
#   llm:
#     default_provider: ollama   # override default for this tool only
#   # tool-specific keys below
