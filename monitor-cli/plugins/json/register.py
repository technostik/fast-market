from plugins.base import PluginManifest
from plugins.json.plugin import JsonPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="json",
        source_plugin_class=JsonPlugin,
        cli_options={},
    )
