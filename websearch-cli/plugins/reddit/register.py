from __future__ import annotations

import click

from plugins.base import PluginManifest
from plugins.reddit.plugin import RedditPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="reddit",
        provider_class=RedditPlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--subreddit"],
                    default=None,
                    help="Restrict the global search to a specific subreddit.",
                ),
                click.Option(
                    ["--sort"],
                    type=click.Choice(["relevance", "new", "top", "comments"]),
                    default="relevance",
                    help="Reddit search sort order.",
                ),
            ],
        },
    )
