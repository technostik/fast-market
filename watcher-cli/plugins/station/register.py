from plugins.base.plugin import PluginManifest
from .plugin import StationProvider
def register(config): return PluginManifest("station", StationProvider, StationProvider.descriptor)
