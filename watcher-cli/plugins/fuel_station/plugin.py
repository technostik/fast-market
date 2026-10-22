from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class FuelStationProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("fuel_station", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = FuelStationProvider
FuelProvider = FuelStationProvider
FuelStationProvider = FuelStationProvider
StationProvider = FuelStationProvider
PrixCarburantsProvider = FuelStationProvider
OpenDataProvider = FuelStationProvider
