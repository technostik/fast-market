from __future__ import annotations
from plugins.base.plugin import ProviderDescriptor
from plugins.carburants.plugin import CarburantsProvider

class CarburantProvider(CarburantsProvider):
    descriptor = ProviderDescriptor("carburant", (), True, CarburantsProvider.descriptor.symbol_help)

# backwards/alias names
CarburantsProvider = CarburantProvider
FuelProvider = CarburantProvider
FuelStationProvider = CarburantProvider
StationProvider = CarburantProvider
PrixCarburantsProvider = CarburantProvider
OpenDataProvider = CarburantProvider
