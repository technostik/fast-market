from plugins.base.plugin import PluginManifest
from .plugin import FredProvider
def register(config): return PluginManifest('fred',FredProvider,FredProvider.descriptor)
