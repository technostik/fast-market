from __future__ import annotations

from plugins.obsidian.plugin import ObsidianPlugin
from plugins.youtube.plugin import YouTubePlugin


def build_plugins(config: dict[str, object]) -> dict[str, object]:
    return {
        "obsidian": ObsidianPlugin(config),
        "youtube": YouTubePlugin(config),
    }
