from __future__ import annotations

import click

from plugins.base import PluginManifest
from plugins.obsidian.plugin import ObsidianPlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the obsidian plugin contributes to the system."""
    return PluginManifest(
        name="obsidian",
        source_plugin_class=ObsidianPlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--since"],
                    default=None,
                    help="Filter by date: only notes updated on or after YYYY-MM-DD.",
                ),
                click.Option(
                    ["--until"],
                    default=None,
                    help="Filter by date: only notes updated on or before YYYY-MM-DD.",
                ),
                click.Option(
                    ["--min-size"],
                    type=int,
                    default=None,
                    help="Minimum note size in characters.",
                ),
                click.Option(
                    ["--max-size"],
                    type=int,
                    default=None,
                    help="Maximum note size in characters.",
                ),
            ],
        },
        api_router=None,
        frontend_js=None,
    )
