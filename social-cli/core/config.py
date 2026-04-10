"""Load configuration for the social CLI.

Unlike other tools in fast-market, social uses its own XDG config layout
under ``~/.config/social/`` with per-backend subdirectories:

    ~/.config/social/twitter/config.yaml
    ~/.config/social/linkedin/config.yaml
    ~/.config/social/substack/config.yaml
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised when required config is missing."""


def _xdg_config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base)
    return Path.home() / ".config"


def _social_config_root() -> Path:
    return _xdg_config_home() / "social"


def load_config() -> dict[str, object]:
    """Load the merged social config.

    Merges:
    1. ``~/.config/social/config.yaml`` (global social settings)
    2. ``~/.config/social/<backend>/config.yaml`` for each backend dir
    """
    root = _social_config_root()
    config: dict = {}

    # Global social config
    global_cfg = root / "config.yaml"
    if global_cfg.exists():
        with open(global_cfg) as f:
            data = yaml.safe_load(f) or {}
        _deep_merge(config, data)

    # Per-backend configs
    if root.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir():
                backend_cfg = child / "config.yaml"
                if backend_cfg.exists():
                    with open(backend_cfg) as f:
                        data = yaml.safe_load(f) or {}
                    _deep_merge(config, data)

    if not config:
        raise ConfigError(
            f"No social config found at {root}.\n"
            f"Create per-backend configs, e.g.:\n"
            f"  mkdir -p {root}/twitter\n"
            f"  cat > {root}/twitter/config.yaml << 'EOF'\n"
            f"  twitter_bearer_token: YOUR_TOKEN\n"
            f"  twitter_api_key: YOUR_KEY\n"
            f"  twitter_api_secret: YOUR_SECRET\n"
            f"  twitter_access_token: YOUR_ACCESS\n"
            f"  twitter_access_token_secret: YOUR_ACCESS_SECRET\n"
            f"  EOF"
        )

    return config


def load_backend_config(backend: str) -> dict:
    """Load config for a specific backend. Raises ConfigError if missing."""
    root = _social_config_root()
    cfg_path = root / backend / "config.yaml"
    if not cfg_path.exists():
        raise ConfigError(
            f"Config not found for backend '{backend}' at {cfg_path}.\n"
            f"Please create it with your {backend} credentials."
        )
    with open(cfg_path) as f:
        data = yaml.safe_load(f) or {}
    return data


def available_backends() -> list[str]:
    """Return list of backends that have a config.yaml."""
    root = _social_config_root()
    backends = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "config.yaml").exists():
                backends.append(child.name)
    return backends


def _deep_merge(base: dict, override: dict) -> None:
    """Merge *override* into *base* in place."""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
