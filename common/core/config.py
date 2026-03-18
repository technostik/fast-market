from __future__ import annotations

import os
import warnings
from pathlib import Path

import yaml

from common.core.paths import get_tool_config


def _resolve_config_path(tool_name: str, path: str | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()

    override_dir = os.environ.get("FASTMARKET_CONFIG_DIR")
    if override_dir:
        return Path(override_dir).expanduser() / f"{tool_name}.yaml"

    deprecated_path = Path("config.yaml")
    if deprecated_path.exists():
        warnings.warn(
            "config.yaml in current directory is deprecated. "
            f"Move to {get_tool_config(tool_name)}",
            DeprecationWarning,
            stacklevel=2,
        )
        return deprecated_path

    return get_tool_config(tool_name)

    override_dir = os.environ.get("FASTMARKET_CONFIG_DIR")
    if override_dir:
        result = Path(override_dir).expanduser() / f"{tool_name}.yaml"
        print(f"[DEBUG] Using FASTMARKET_CONFIG_DIR override: {result}")
        return result

    deprecated_path = Path("config.yaml")
    if deprecated_path.exists():
        warnings.warn(
            "config.yaml in current directory is deprecated. "
            f"Move to {get_tool_config(tool_name)}",
            DeprecationWarning,
            stacklevel=2,
        )
        print(f"[DEBUG] Using deprecated config.yaml: {deprecated_path}")
        return deprecated_path

    result = get_tool_config(tool_name)
    print(f"[DEBUG] Using get_tool_config: {result}")
    return result


def load_tool_config(tool_name: str, path: str | None = None) -> dict[str, object]:
    """Load a fast-market tool config mapping from disk."""
    cfg_path = _resolve_config_path(tool_name, path)
    if not cfg_path.exists():
        return {}
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{cfg_path.name} must be a mapping")
    return data


def load_config(path: str | None = None) -> dict[str, object]:
    """Load corpus config for backward compatibility."""
    return load_tool_config("corpus", path)
