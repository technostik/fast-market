from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from common.core.yaml_utils import dump_yaml


DEFAULT_PROMPT_TEMPLATE = """You are a task execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

# Your Task
{task_description}
{params_section}

# Working Directory
All commands execute in: `{workdir}`

You can read and write files in this directory. Relative paths are resolved from here.

---

{command_docs}

---

# How to Work

1. **Understand the task**: Break it down into clear steps
2. **Explore first**: Use `ls` and `cat` to understand what files exist
3. **Execute incrementally**: Run one command, check the result, then decide next step
4. **Handle errors**: If a command fails, read the error message and try a different approach
5. **Stay focused**: Only use commands that advance the task
6. **Finish clearly**: When done, summarize what you accomplished (without making tool calls)

# Critical Rules

- **Only use listed commands** - others will be rejected
- **Work within the directory** - you cannot escape `{workdir}`
- **Check outputs** - always verify command results before proceeding
- **Be efficient** - prefer one good command over many guesses
- **Ask for help** - if truly stuck, explain what you need

"""


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
