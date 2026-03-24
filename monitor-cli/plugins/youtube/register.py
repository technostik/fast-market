import click

from plugins.base import PluginManifest
from plugins.youtube.plugin import YouTubePlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="youtube",
        source_plugin_class=YouTubePlugin,
        cli_options={},
    )
