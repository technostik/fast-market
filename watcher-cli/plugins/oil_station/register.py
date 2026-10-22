from plugins.base.plugin import PluginManifest
from .plugin import OilStationProvider
def register(config): return PluginManifest("oil_station", OilStationProvider, OilStationProvider.descriptor)
