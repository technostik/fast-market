from __future__ import annotations

import click

from plugins.base import PluginManifest
from plugins.hacker_news.plugin import HackerNewsPlugin
from commands.completion import HackerNewsTagsParamType


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="hacker_news",
        provider_class=HackerNewsPlugin,
        cli_options={
            "search": [
                click.Option(
                    ["--tags"],
                    type=HackerNewsTagsParamType(),
                    default=None,
                    help="Hacker News tag filter (e.g. story, comment). Overrides config.",
                ),
                click.Option(
                    ["--points"],
                    type=int,
                    default=None,
                    help="Minimum points (score) for returned stories.",
                ),
            ],
        },
    )
