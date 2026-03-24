from plugins.base import PluginManifest
from plugins.yt_search.plugin import YouTubeSearchPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="yt-search",
        source_plugin_class=YouTubeSearchPlugin,
        cli_options={},
    )
