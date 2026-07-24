from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.config import load_tool_config, requires_common_config
from common.core.registry import discover_commands, discover_plugins

requires_common_config("rag", ["llm"])

main = create_cli_group(
    "rag",
    description="Vectorless reasoning-based RAG with hierarchical document trees and agentic retrieval.",
)
_TOOL_ROOT = Path(__file__).resolve().parents[1]


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    config = load_tool_config("rag")
    plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)


_load()

if __name__ == "__main__":
    main()
