from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class PrixCarburantsProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("prix_carburants", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = PrixCarburantsProvider
FuelProvider = PrixCarburantsProvider
FuelStationProvider = PrixCarburantsProvider
StationProvider = PrixCarburantsProvider
PrixCarburantsProvider = PrixCarburantsProvider
OpenDataProvider = PrixCarburantsProvider
