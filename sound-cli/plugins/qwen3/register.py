from __future__ import annotations

from plugins.base import PluginManifest
from plugins.qwen3.plugin import Qwen3TTSPlugin


def register(config: dict) -> PluginManifest:
    return PluginManifest(
        name="qwen3",
        engine_class=Qwen3TTSPlugin,
        cli_options={},
        api_router=None,
    )
