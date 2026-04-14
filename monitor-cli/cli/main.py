from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.config import load_tool_config, requires_common_config, ConfigError
from common.core.registry import discover_commands, discover_plugins

requires_common_config("monitor", [])

main = create_cli_group("monitor")
_TOOL_ROOT = Path(__file__).resolve().parents[1]
_load_error: Exception | None = None


def _load() -> None:
    global _load_error
    logging.basicConfig(level=logging.CRITICAL, force=True)
    try:
        config = load_tool_config("monitor")
    except ConfigError as e:
        _load_error = e
        # Still discover commands so config edit/locate can work
        config = {}
    plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


_load()


def get_load_error() -> Exception | None:
    """Return the config load error if any."""
    return _load_error


if __name__ == "__main__":
    main()
