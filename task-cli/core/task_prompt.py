from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE as DEFAULT_PROMPT_TEMPLATE,
)
from common.core.yaml_utils import dump_yaml


@dataclass
class TaskPromptConfig:
    name: str
    description: str = ""
    template: str = ""
    variables: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> TaskPromptConfig | None:
        """Load prompt configuration from a YAML file."""
        if not path.exists():
            return None

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return None

        if not isinstance(data, dict):
            return None

        return cls(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            template=data.get("template", ""),
            variables=data.get("variables", {}),
        )

    def to_yaml(self) -> str:
        """Serialize prompt configuration to YAML."""
        data = {
            "name": self.name,
            "description": self.description,
            "template": self.template,
        }
        if self.variables:
            data["variables"] = self.variables
        return dump_yaml(data, sort_keys=False)

    def save(self, path: Path) -> None:
        """Save prompt configuration to a YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_yaml(), encoding="utf-8")

    def render(self, **kwargs: str) -> str:
        """Render the prompt template with provided variables."""
        return self.template.format(**kwargs)

    def validate(self) -> list[str]:
        """Validate the prompt configuration. Returns list of errors."""
        errors = []
        if not self.name:
            errors.append("name is required")
        if not self.template:
            errors.append("template is required")
        return errors
