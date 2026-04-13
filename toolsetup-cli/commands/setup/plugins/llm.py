from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import yaml

from common.core.yaml_utils import dump_yaml
from common.core.paths import get_llm_config_path
from commands.setup.plugins import ConfigPlugin, register_plugin


class LLMPlugin(ConfigPlugin):
    name: ClassVar[str] = "llm"
    display_name: ClassVar[str] = "LLM Providers"

    def config_path(self) -> Path:
        return get_llm_config_path()

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
            "default_provider": "ollama",
            "providers": {
                "ollama": {
                    "model": "llama3.2",
                    "base_url": "http://127.0.0.1:11434",
                }
            },
        }


register_plugin(LLMPlugin())
