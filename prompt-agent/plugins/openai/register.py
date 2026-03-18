from __future__ import annotations

from plugins.base import PluginManifest
from plugins.openai.plugin import OpenAIProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="openai", provider_class=OpenAIProvider)
