from __future__ import annotations

from plugins.base import PluginManifest
from plugins.ollama.plugin import OllamaProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="ollama", provider_class=OllamaProvider)
