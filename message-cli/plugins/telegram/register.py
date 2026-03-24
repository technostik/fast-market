from __future__ import annotations

import click
from plugins.base import PluginManifest
from plugins.telegram.plugin import TelegramPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="telegram",
        source_plugin_class=TelegramPlugin,
        cli_options={
            "ask": [
                click.Option(
                    ["--timeout"],
                    type=int,
                    default=None,
                    help="Timeout in seconds (0 = no timeout, default from config).",
                ),
            ],
            "alert": [
                click.Option(
                    ["--wait"],
                    is_flag=True,
                    default=False,
                    help="Wait for acknowledgment instead of fire-and-forget.",
                ),
                click.Option(
                    ["--timeout"],
                    type=int,
                    default=None,
                    help="Timeout in seconds for --wait (0 = no timeout, default from config).",
                ),
            ],
        },
    )
