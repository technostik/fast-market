from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class GazoleProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("gazole", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = GazoleProvider
FuelProvider = GazoleProvider
FuelStationProvider = GazoleProvider
StationProvider = GazoleProvider
PrixCarburantsProvider = GazoleProvider
OpenDataProvider = GazoleProvider
