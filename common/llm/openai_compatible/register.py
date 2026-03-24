from __future__ import annotations

from common.llm.base import PluginManifest
from common.llm.openai_compatible.provider import OpenAICompatibleProvider


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="openai-compatible", provider_class=OpenAICompatibleProvider
    )
