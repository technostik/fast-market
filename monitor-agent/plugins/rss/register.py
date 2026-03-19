import click

from plugins.base import PluginManifest
from plugins.rss.plugin import RSSPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="rss",
        source_plugin_class=RSSPlugin,
        cli_options={},
    )
