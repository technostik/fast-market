from __future__ import annotations

import logging
from pathlib import Path

import click
from common.cli.base import create_cli_group
from common.core.config import load_tool_config, requires_common_config
from common.core.registry import discover_commands, discover_plugins

requires_common_config("websearch", [])

main = create_cli_group(
    "websearch",
    description="Search the web via pluggable providers (Google News, Reddit, Hacker News).",
)
_TOOL_ROOT = Path(__file__).resolve().parents[1]


class WebsearchGroup(click.Group):
    """Group that routes a bare `websearch "<query>"` to the `search` command.

    `websearch setup ...` and `websearch search ...` keep working because their
    first token is a real subcommand. Only when the first token is not a known
    subcommand do we prepend "search" so the remaining tokens become its arguments.
    """

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            return super().resolve_command(ctx, ["search", *args])


main.__class__ = WebsearchGroup


def _load() -> None:
    logging.basicConfig(level=logging.CRITICAL, force=True)
    config = load_tool_config("websearch")
    plugin_manifests = discover_plugins(config, tool_root=_TOOL_ROOT)
    command_manifests = discover_commands(plugin_manifests, tool_root=_TOOL_ROOT)
    for command_manifest in command_manifests.values():
        main.add_command(command_manifest.click_command)


_load()

if __name__ == "__main__":
    main()
