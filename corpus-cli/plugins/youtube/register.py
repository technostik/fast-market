from __future__ import annotations

import click

from plugins.base import PluginManifest
from plugins.youtube.plugin import YouTubePlugin


def register(config: dict) -> PluginManifest:
    """Declare everything the youtube plugin contributes to the system."""
    return PluginManifest(
        name="youtube",
        source_plugin_class=YouTubePlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--type", "video_type"],
                    type=click.Choice(["short", "long"]),
                    default=None,
                    help="Filter by video type (short ≤60s, long >60s).",
                ),
                click.Option(
                    ["--min-duration"],
                    type=int,
                    default=None,
                    help="Minimum video duration in seconds.",
                ),
                click.Option(
                    ["--max-duration"],
                    type=int,
                    default=None,
                    help="Maximum video duration in seconds.",
                ),
                click.Option(
                    ["--privacy-status", "--privacy", "privacy_status"],
                    type=click.Choice(
                        ["public", "unlisted", "private", "members", "unknown"]
                    ),
                    default=None,
                    help="Filter by YouTube privacy status.",
                ),
            ],
            "list": [
                click.Option(
                    ["--type", "video_type"],
                    type=click.Choice(["short", "long"]),
                    default=None,
                    help="Filter by video type (short ≤60s, long >60s).",
                ),
                click.Option(
                    ["--min-duration"],
                    type=int,
                    default=None,
                    help="Minimum video duration in seconds.",
                ),
                click.Option(
                    ["--max-duration"],
                    type=int,
                    default=None,
                    help="Maximum video duration in seconds.",
                ),
                click.Option(
                    ["--privacy-status", "--privacy", "privacy_status"],
                    type=click.Choice(
                        ["public", "unlisted", "private", "members", "unknown"]
                    ),
                    default=None,
                    help="Filter by YouTube privacy status.",
                ),
            ],
        },
        api_router=None,
        frontend_js=None,
    )
