from plugins.base import PluginManifest
from plugins.channel_list.plugin import ChannelListPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="channel_list",
        source_plugin_class=ChannelListPlugin,
        cli_options={},
    )
