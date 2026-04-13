from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import yaml

from common.core.yaml_utils import dump_yaml
from common.core.paths import get_common_config_path
from commands.setup.plugins import ConfigPlugin, register_plugin


class WorkdirPlugin(ConfigPlugin):
    """Manages the common/config.yaml (workdir and global settings)."""

    name: ClassVar[str] = "workdir"
    display_name: ClassVar[str] = "Workdir (common)"

    def config_path(self) -> Path:
        return get_common_config_path()

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
            "workdir": str(Path.home() / "fast-market-work"),
            "workdir_root": str(Path.home() / "fast-market-work"),
            "workdir_prefix": "work-",
        }


register_plugin(WorkdirPlugin())
