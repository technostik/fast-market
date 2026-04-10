from __future__ import annotations

import sys
from pathlib import Path

import click

from common.cli.helpers import out as _out
from common.core.registry import build_plugins

_TOOL_ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    """Load config, raising a clear error if missing."""
    from core.config import ConfigError, load_config as _load_config

    try:
        return _load_config()
    except ConfigError:
        raise
    except Exception:
        raise ConfigError(
            "Failed to load social config. "
            "Ensure your backend config exists under ~/.config/social/<backend>/config.yaml"
        )


def build_plugin(config: dict, plugin_name: str = "twitter"):
    """Instantiate a single plugin by name."""
    plugins = build_plugins(config, tool_root=_TOOL_ROOT, plugin_package="plugins")
    if plugin_name not in plugins:
        available = list(plugins.keys())
        raise click.ClickException(
            f"Backend '{plugin_name}' not found. Available: {available}"
        )
    return plugins[plugin_name]


def out(data: object, fmt: str) -> None:
    _out(data, fmt)


def read_stdin() -> str:
    """Read text from stdin. Returns empty string if no stdin."""
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read().strip()
