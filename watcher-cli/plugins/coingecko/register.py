from plugins.base.plugin import PluginManifest
from .plugin import CoinGeckoProvider
def register(config): return PluginManifest('coingecko',CoinGeckoProvider,CoinGeckoProvider.descriptor)
