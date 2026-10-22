from plugins.base.plugin import PluginManifest
from .plugin import GazoleProvider
def register(config): return PluginManifest("gazole", GazoleProvider, GazoleProvider.descriptor)
