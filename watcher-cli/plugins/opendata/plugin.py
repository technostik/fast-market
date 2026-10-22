from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class OpendataProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("opendata", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = OpendataProvider
FuelProvider = OpendataProvider
FuelStationProvider = OpendataProvider
StationProvider = OpendataProvider
PrixCarburantsProvider = OpendataProvider
OpenDataProvider = OpendataProvider
