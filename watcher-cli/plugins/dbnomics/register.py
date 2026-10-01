from plugins.base.plugin import PluginManifest
from .plugin import DBnomicsProvider
def register(config): return PluginManifest('dbnomics',DBnomicsProvider,DBnomicsProvider.descriptor)
