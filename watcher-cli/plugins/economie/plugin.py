from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class EconomieProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("economie", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = EconomieProvider
FuelProvider = EconomieProvider
FuelStationProvider = EconomieProvider
StationProvider = EconomieProvider
PrixCarburantsProvider = EconomieProvider
OpenDataProvider = EconomieProvider
