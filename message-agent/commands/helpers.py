from __future__ import annotations

import sys
from pathlib import Path

import click

from common.cli.helpers import out as _out
from common.core.registry import build_plugins

_TOOL_ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    from core.config import load_config as _load_config

    return _load_config()


def build_plugin(config: dict, plugin_name: str = "telegram"):
    plugins = build_plugins(config, tool_root=_TOOL_ROOT, plugin_package="plugins")
    if plugin_name not in plugins:
        raise ValueError(
            f"Plugin '{plugin_name}' not found. Available: {list(plugins.keys())}"
        )
    return plugins[plugin_name]


def out(data: object, fmt: str) -> None:
    _out(data, fmt)


def read_stdin() -> str:
    if sys.stdin.isatty():
        raise click.ClickException(
            "No stdin available (pipe content into this command)"
        )
    content = sys.stdin.read().strip()
    if not content:
        raise click.ClickException("No input from stdin")
    return content
