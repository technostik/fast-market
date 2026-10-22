from plugins.base.plugin import PluginManifest
from .plugin import FuelProvider
def register(config): return PluginManifest("fuel", FuelProvider, FuelProvider.descriptor)
