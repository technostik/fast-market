from plugins.base.plugin import PluginManifest
from .plugin import KrakenProvider
def register(config): return PluginManifest('kraken', KrakenProvider, KrakenProvider.descriptor)
