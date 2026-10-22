from plugins.base.plugin import PluginManifest
from .plugin import StationsProvider
def register(config): return PluginManifest("stations", StationsProvider, StationsProvider.descriptor)
