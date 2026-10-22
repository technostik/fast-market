from plugins.base.plugin import PluginManifest
from .plugin import OpendataProvider
def register(config): return PluginManifest("opendata", OpendataProvider, OpendataProvider.descriptor)
