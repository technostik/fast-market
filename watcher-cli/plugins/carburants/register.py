from plugins.base.plugin import PluginManifest
from .plugin import CarburantsProvider
def register(config): return PluginManifest('carburants', CarburantsProvider, CarburantsProvider.descriptor)
