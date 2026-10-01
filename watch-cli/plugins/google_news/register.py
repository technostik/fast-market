from plugins.base.plugin import PluginManifest,ProviderDescriptor
from .plugin import GoogleNewsProvider
def register(config): return PluginManifest('google_news',GoogleNewsProvider,ProviderDescriptor('google_news',(),False,'RSS news provider'))
