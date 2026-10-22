from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class FuelProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("fuel", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = FuelProvider
FuelProvider = FuelProvider
FuelStationProvider = FuelProvider
StationProvider = FuelProvider
PrixCarburantsProvider = FuelProvider
OpenDataProvider = FuelProvider
