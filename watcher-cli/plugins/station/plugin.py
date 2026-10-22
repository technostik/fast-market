from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class StationProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("station", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = StationProvider
FuelProvider = StationProvider
FuelStationProvider = StationProvider
StationProvider = StationProvider
PrixCarburantsProvider = StationProvider
OpenDataProvider = StationProvider
