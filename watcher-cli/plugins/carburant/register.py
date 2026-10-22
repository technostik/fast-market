from plugins.base.plugin import PluginManifest
from .plugin import CarburantProvider
def register(config): return PluginManifest("carburant", CarburantProvider, CarburantProvider.descriptor)
