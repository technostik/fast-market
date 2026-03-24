from __future__ import annotations

from common.llm.base import PluginManifest
from common.llm.ollama.provider import OllamaProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="ollama", provider_class=OllamaProvider)
