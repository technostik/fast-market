from plugins.base.plugin import PluginManifest
from .plugin import CnbcProvider
def register(config): return PluginManifest('cnbc',CnbcProvider,CnbcProvider.descriptor)
