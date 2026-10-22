from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class StationsProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("stations", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = StationsProvider
FuelProvider = StationsProvider
FuelStationProvider = StationsProvider
StationProvider = StationsProvider
PrixCarburantsProvider = StationsProvider
OpenDataProvider = StationsProvider
