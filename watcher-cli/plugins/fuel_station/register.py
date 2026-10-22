from plugins.base.plugin import PluginManifest
from .plugin import FuelStationProvider
def register(config): return PluginManifest("fuel_station", FuelStationProvider, FuelStationProvider.descriptor)
