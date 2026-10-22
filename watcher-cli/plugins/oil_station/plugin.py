from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class OilStationProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("oil_station", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = OilStationProvider
FuelProvider = OilStationProvider
FuelStationProvider = OilStationProvider
StationProvider = OilStationProvider
PrixCarburantsProvider = OilStationProvider
OpenDataProvider = OilStationProvider
