from plugins.base.plugin import PluginManifest
from .plugin import CoinbaseProvider
def register(config): return PluginManifest('coinbase', CoinbaseProvider, CoinbaseProvider.descriptor)
