from __future__ import annotations

from common.llm.base import PluginManifest
from common.llm.groq.provider import GroqProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(name="groq", provider_class=GroqProvider)
