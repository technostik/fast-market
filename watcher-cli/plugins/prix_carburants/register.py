from plugins.base.plugin import PluginManifest
from .plugin import PrixCarburantsProvider
def register(config): return PluginManifest("prix_carburants", PrixCarburantsProvider, PrixCarburantsProvider.descriptor)
