from __future__ import annotations

from pathlib import Path

import click
import yaml

from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_COMMAND_DOCS_TEMPLATES,
    DEFAULT_FASTMARKET_TOOLS,
    DEFAULT_SYSTEM_COMMANDS,
    default_fastmarket_tools_dict,
)
from common.core.config import load_agent_config, save_agent_config
from common.core.yaml_utils import dump_yaml


def load_task_config() -> dict:
    """Load agent config from the common file.

    Returns the full agent config dict (top-level keys like fastmarket_tools,
    system_commands, agent_prompt, etc.). Returns {} if file doesn't exist.
    """
    return load_agent_config()


def save_task_config(config: dict) -> None:
    """Save agent config to the common file.

    Writes the full agent config dict directly to ~/.config/fast-market/common/agent/config.yaml.
    """
    save_agent_config(config)


def init_task_config(config: dict | None = None) -> dict:
    """Initialize task config with defaults if not present.

    Loads from the common agent config file first, then applies defaults
    for any missing keys.
    """
    if config is None:
        config = load_task_config()
    else:
        file_config = load_task_config()
        config = {**file_config, **config}

    if not isinstance(config, dict):
        raise ValueError("agent config must be a mapping")

    config.setdefault("fastmarket_tools", default_fastmarket_tools_dict())
    config.setdefault("system_commands", list(DEFAULT_SYSTEM_COMMANDS))
    config.setdefault("max_iterations", 20)
    config.setdefault("default_timeout", 60)
    config.setdefault("default_workdir", None)

    if "agent_prompt" not in config:
        config["agent_prompt"] = {
            "active": "default",
            "templates": {
                "default": {
                    "description": "Default task execution prompt",
                    "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                },
            },
        }

    if "command_docs" not in config:
        config["command_docs"] = {
            "active": "minimal",
            "templates": dict(DEFAULT_COMMAND_DOCS_TEMPLATES),
        }

    if "learn_analysis_prompt" not in config:
        from common.learn import LEARN_ANALYSIS_PROMPT_TEMPLATE

        config["learn_analysis_prompt"] = LEARN_ANALYSIS_PROMPT_TEMPLATE

    if "learn_result_template" not in config:
        from common.learn import LEARN_RESULT_TEMPLATE

        config["learn_result_template"] = LEARN_RESULT_TEMPLATE

    return config
