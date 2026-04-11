from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.registry import discover_commands, discover_plugins

main = create_cli_group(
    "browser",
    description="Control a Chromium-based browser via CDP for agent automation."
)
_TOOL_ROOT = Path(__file__).resolve().parents[1]


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    from core.config import load_config

    config = load_config()
    # No plugins for browser-cli, pass empty dict
    plugin_manifests: dict = {}
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


_load()
