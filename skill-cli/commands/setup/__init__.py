from __future__ import annotations

import yaml

from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_EVALUATION_PROMPT,
    DEFAULT_FASTMARKET_TOOLS,
    DEFAULT_PLAN_PROMPT,
    DEFAULT_PREPARATION_PROMPT,
    DEFAULT_SYSTEM_COMMANDS,
)
from common.core.config import _resolve_config_path
from common.core.yaml_utils import dump_yaml
from common.learn import (
    SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE as DEFAULT_SKILL_FROM_DESCRIPTION_PROMPT,
)


def load_skill_agent_config() -> dict:
    """Load skill agent config from file, returning the 'agent' sub-dict.

    Returns {} if config file doesn't exist or has no 'agent' section.
    """
    config_path = _resolve_config_path("skill")
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("agent", {})
    return {}


def save_skill_agent_config(agent_config: dict) -> None:
    """Save skill agent config to file.

    Reads the full skill config, updates the 'agent' section, and writes back.
    Preserves all other top-level keys in the config file.
    """
    config_path = _resolve_config_path("skill")
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    data["agent"] = agent_config

    with open(config_path, "w") as f:
        f.write(dump_yaml(data, sort_keys=False))


def default_skill_agent_config() -> dict:
    """Return a fresh default agent config, ignoring any file on disk."""
    return {
        "fastmarket_tools": dict(DEFAULT_FASTMARKET_TOOLS),
        "system_commands": list(DEFAULT_SYSTEM_COMMANDS),
        "max_iterations": 20,
        "default_timeout": 60,
        "agent_prompt": {
            "active": "default",
            "templates": {
                "default": {
                    "description": "Default skill execution prompt",
                    "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                },
            },
        },
        "command_docs": {
            "active": "minimal",
            "templates": {
                "minimal": {
                    "description": "Brief with descriptions",
                    "template": "{fastmarket_tools_brief}{system_commands_minimal}",
                },
            },
        },
        "preparation_prompt": DEFAULT_PREPARATION_PROMPT,
        "evaluation_prompt": DEFAULT_EVALUATION_PROMPT,
        "plan_prompt": DEFAULT_PLAN_PROMPT,
        "skill_from_description_prompt": DEFAULT_SKILL_FROM_DESCRIPTION_PROMPT,
    }


def init_skill_agent_config(agent_dict: dict | None = None) -> dict:
    """Initialize skill agent config with defaults if not present.

    Loads from file first, then applies defaults for any missing keys.
    """
    if agent_dict is None:
        agent_dict = load_skill_agent_config()
    else:
        file_config = load_skill_agent_config()
        agent_dict = {**file_config, **agent_dict}

    if not isinstance(agent_dict, dict):
        raise ValueError("agent config must be a mapping")

    agent_dict.setdefault("fastmarket_tools", dict(DEFAULT_FASTMARKET_TOOLS))
    agent_dict.setdefault("system_commands", list(DEFAULT_SYSTEM_COMMANDS))
    agent_dict.setdefault("max_iterations", 20)
    agent_dict.setdefault("default_timeout", 60)

    if "agent_prompt" not in agent_dict:
        agent_dict["agent_prompt"] = {
            "active": "default",
            "templates": {
                "default": {
                    "description": "Default skill execution prompt",
                    "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                },
            },
        }

    if "command_docs" not in agent_dict:
        agent_dict["command_docs"] = {
            "active": "minimal",
            "templates": {
                "minimal": {
                    "description": "Brief with descriptions",
                    "template": "{fastmarket_tools_brief}{system_commands_minimal}",
                },
            },
        }

    agent_dict.setdefault("preparation_prompt", DEFAULT_PREPARATION_PROMPT)
    agent_dict.setdefault("evaluation_prompt", DEFAULT_EVALUATION_PROMPT)
    agent_dict.setdefault("plan_prompt", DEFAULT_PLAN_PROMPT)
    agent_dict.setdefault(
        "skill_from_description_prompt", DEFAULT_SKILL_FROM_DESCRIPTION_PROMPT
    )

    return agent_dict
