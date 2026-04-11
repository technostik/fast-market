from __future__ import annotations

from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_COMMAND_DOCS_TEMPLATES,
    DEFAULT_EVALUATION_PROMPT,
    DEFAULT_FASTMARKET_TOOLS,
    DEFAULT_PLAN_PROMPT,
    DEFAULT_PREPARATION_PROMPT,
    DEFAULT_SYSTEM_COMMANDS,
    default_fastmarket_tools_dict,
)
from common.core.config import load_agent_config, save_agent_config
from common.learn import (
    SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE as DEFAULT_SKILL_FROM_DESCRIPTION_PROMPT,
)


def load_skill_agent_config() -> dict:
    """Load agent config from the common file.

    Returns the full agent config dict (top-level keys like fastmarket_tools,
    system_commands, agent_prompt, etc.). Returns {} if file doesn't exist.
    """
    return load_agent_config()


def save_skill_agent_config(agent_config: dict) -> None:
    """Save agent config to the common file.

    Writes the full agent config dict directly to ~/.config/fast-market/common/agent/config.yaml.
    """
    save_agent_config(agent_config)


def default_skill_agent_config() -> dict:
    """Return a fresh default agent config, ignoring any file on disk."""
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
        "skill_from_description_prompt": DEFAULT_SKILL_FROM_DESCRIPTION_PROMPT,
    }


def init_skill_agent_config(agent_dict: dict | None = None) -> dict:
    """Initialize agent config with defaults if not present.

    Loads from the common agent config file first, then applies defaults
    for any missing keys.
    """
    if agent_dict is None:
        agent_dict = load_skill_agent_config()
    else:
        file_config = load_skill_agent_config()
        agent_dict = {**file_config, **agent_dict}

    if not isinstance(agent_dict, dict):
        raise ValueError("agent config must be a mapping")

    agent_dict.setdefault("fastmarket_tools", default_fastmarket_tools_dict())
    agent_dict.setdefault("system_commands", list(DEFAULT_SYSTEM_COMMANDS))
    agent_dict.setdefault("max_iterations", 20)
    agent_dict.setdefault("default_timeout", 60)

    if "agent_prompt" not in agent_dict:
        agent_dict["agent_prompt"] = {
            "active": "default",
            "templates": {
                "default": {
                    "description": "Default agent execution prompt",
                    "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                },
            },
        }

    if "command_docs" not in agent_dict:
        agent_dict["command_docs"] = {
            "active": "minimal",
            "templates": dict(DEFAULT_COMMAND_DOCS_TEMPLATES),
        }

    agent_dict.setdefault("preparation_prompt", DEFAULT_PREPARATION_PROMPT)
    agent_dict.setdefault("evaluation_prompt", DEFAULT_EVALUATION_PROMPT)
    agent_dict.setdefault("plan_prompt", DEFAULT_PLAN_PROMPT)
    agent_dict.setdefault(
        "skill_from_description_prompt", DEFAULT_SKILL_FROM_DESCRIPTION_PROMPT
    )

    return agent_dict
