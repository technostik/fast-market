from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import yaml

from common.core.yaml_utils import dump_yaml
from common.core.paths import get_agent_config_path
from commands.setup.plugins import ConfigPlugin, register_plugin


class AgentPlugin(ConfigPlugin):
    name: ClassVar[str] = "agent"
    display_name: ClassVar[str] = "Agent Configuration"

    def config_path(self) -> Path:
        return get_agent_config_path()

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
        from common.agent.prompts import (
            DEFAULT_AGENT_PROMPT_TEMPLATE,
            DEFAULT_SYSTEM_COMMANDS,
            default_fastmarket_tools_dict,
            DEFAULT_EVALUATION_PROMPT,
            DEFAULT_PLAN_PROMPT,
            DEFAULT_PREPARATION_PROMPT,
            DEFAULT_COMMAND_DOCS_TEMPLATES,
        )
        from common.learn import SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE

        return {
            "fastmarket_tools": default_fastmarket_tools_dict(),
            "system_commands": list(DEFAULT_SYSTEM_COMMANDS),
            "max_iterations": 20,
            "default_timeout": 60,
            "agent_prompt": {
                "active": "default",
                "templates": {
                    "default": {
                        "description": "Default agent execution prompt",
                        "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                    },
                },
            },
            "command_docs": {
                "active": "minimal",
                "templates": dict(DEFAULT_COMMAND_DOCS_TEMPLATES),
            },
            "preparation_prompt": DEFAULT_PREPARATION_PROMPT,
            "evaluation_prompt": DEFAULT_EVALUATION_PROMPT,
            "plan_prompt": DEFAULT_PLAN_PROMPT,
            "skill_from_description_prompt": SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE,
        }


register_plugin(AgentPlugin())
