from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class FuelsProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("fuels", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = FuelsProvider
FuelProvider = FuelsProvider
FuelStationProvider = FuelsProvider
StationProvider = FuelsProvider
PrixCarburantsProvider = FuelsProvider
OpenDataProvider = FuelsProvider
