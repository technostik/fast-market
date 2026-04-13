from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import yaml

from common.core.yaml_utils import dump_yaml
from common.core.paths import get_youtube_config_path
from commands.setup.plugins import ConfigPlugin, register_plugin


class YouTubePlugin(ConfigPlugin):
    name: ClassVar[str] = "youtube"
    display_name: ClassVar[str] = "YouTube (shared)"

    def config_path(self) -> Path:
        return get_youtube_config_path()

    def load(self) -> dict:
        path = self.config_path()
        if not path.exists():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, config: dict) -> None:
        path = self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_yaml(config, sort_keys=False), encoding="utf-8")

    def default_config(self) -> dict:
        return {
            "channel_id": "",
            "quota_limit": 10000,
            "client_secret_path": "~/.config/fast-market/common/youtube/client_secret.json",
        }


register_plugin(YouTubePlugin())
