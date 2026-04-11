from __future__ import annotations

import logging
from pathlib import Path

from common.cli.base import create_cli_group
from common.core.registry import discover_commands, discover_plugins

main = create_cli_group(
    "browser",
    description=(
        "Control a Chromium-based browser via CDP for agent automation.\n\n"
        "See https://github.com/vercel-labs/agent-browser for full command reference."
    ),
)
_TOOL_ROOT = Path(__file__).resolve().parents[1]

_prompt_manager = None


def get_browser_prompt_manager():
    """Get the browser prompt manager instance."""
    return _prompt_manager


def _load() -> None:
    global _prompt_manager
    logging.basicConfig(level=logging.CRITICAL, force=True)
    from core.config import load_config
    from commands.run.browser_loop import BROWSER_DEFAULT_PROMPTS
    from common.prompt import get_prompt_manager, register_commands

    config = load_config()
    # No plugins for browser-cli, pass empty dict
    plugin_manifests: dict = {}
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for cmd in command_manifests.values():
        main.add_command(cmd.click_command)

    # Register prompt service
    _prompt_manager = get_prompt_manager("browser", BROWSER_DEFAULT_PROMPTS)
    register_commands(main, "browser", BROWSER_DEFAULT_PROMPTS)


_load()
