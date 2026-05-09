from plugins.base import PluginManifest
from plugins.directory.plugin import DirectoryPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="directory",
        source_plugin_class=DirectoryPlugin,
        cli_options={},
    )
