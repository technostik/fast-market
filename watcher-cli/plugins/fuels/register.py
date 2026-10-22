from plugins.base.plugin import PluginManifest
from .plugin import FuelsProvider
def register(config): return PluginManifest("fuels", FuelsProvider, FuelsProvider.descriptor)
