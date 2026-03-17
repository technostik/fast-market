from __future__ import annotations

import os
import warnings
from pathlib import Path

import yaml

from core.paths import get_tool_config


def _resolve_config_path(path: str | None) -> Path:
    if path is not None:
        return Path(path)

    override_dir = os.environ.get("FASTMARKET_CONFIG_DIR")
    if override_dir:
        return Path(override_dir) / "corpus.yaml"

    deprecated_path = Path("config.yaml")
    if deprecated_path.exists():
        warnings.warn(
            f"config.yaml in current directory is deprecated. "
            f"Move to {get_tool_config('corpus')}",
            DeprecationWarning,
            stacklevel=2,
        )
        return deprecated_path

    return get_tool_config("corpus")


def load_config(path: str | None = None) -> dict[str, object]:
    cfg_path = _resolve_config_path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{cfg_path.name} must be a mapping")
    return data
