from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.config import load_config
from common.core.registry import discover_commands, discover_plugins

main = create_cli_group("corpus")
_TOOL_ROOT = Path(__file__).resolve().parents[1]


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    config = load_config()
    plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for command_manifest in command_manifests.values():
        main.add_command(command_manifest.click_command)


_load()

if __name__ == "__main__":
    main()
