from __future__ import annotations

from pathlib import Path

import click
import yaml

from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_COMMAND_DOCS_TEMPLATES,
    DEFAULT_FASTMARKET_TOOLS,
    DEFAULT_SYSTEM_COMMANDS,
)
from common.core.config import _resolve_config_path, load_tool_config, save_tool_config
from common.core.yaml_utils import dump_yaml


def load_task_config() -> dict:
    """Load task config from file, returning dict with task key.

    Handles both formats:
    - Root-level: {fastmarket_tools: ..., system_commands: ...}
    - Wrapped: {task: {fastmarket_tools: ..., system_commands: ...}}
    """
    config_path = _resolve_config_path("task")
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        if "task" in data:
            return data
        return {"task": data}
    return {}


def save_task_config(config: dict) -> None:
    """Save task config to file.

    Expects config to have 'task' key, saves it at root level for cleaner YAML.
    """
    config_path = _resolve_config_path("task")
    config_path.parent.mkdir(parents=True, exist_ok=True)

    task_data = config.get("task", config)
    with open(config_path, "w") as f:
        f.write(dump_yaml(task_data, sort_keys=False))


def init_task_config(config: dict | None = None) -> dict:
    """Initialize task config with defaults if not present.

    Loads from file first, then applies defaults for any missing keys.
    """
    if config is None:
        config = load_task_config()
    else:
        file_config = load_task_config()
        config = {**file_config, **config}

    task = config.setdefault("task", {})
    if not isinstance(task, dict):
        raise ValueError("task config must be a mapping")

    task.setdefault("fastmarket_tools", dict(DEFAULT_FASTMARKET_TOOLS))
    task.setdefault("system_commands", list(DEFAULT_SYSTEM_COMMANDS))
    task.setdefault("max_iterations", 20)
    task.setdefault("default_timeout", 60)
    task.setdefault("default_workdir", None)

    if "agent_prompt" not in task:
        task["agent_prompt"] = {
            "active": "default",
            "templates": {
                "default": {
                    "description": "Default task execution prompt",
                    "template": DEFAULT_AGENT_PROMPT_TEMPLATE,
                },
            },
        }

    if "command_docs" not in task:
        task["command_docs"] = {
            "active": "minimal",
            "templates": dict(DEFAULT_COMMAND_DOCS_TEMPLATES),
        }

    if "learn_analysis_prompt" not in task:
        from common.learn import LEARN_ANALYSIS_PROMPT_TEMPLATE

        task["learn_analysis_prompt"] = LEARN_ANALYSIS_PROMPT_TEMPLATE

    if "learn_result_template" not in task:
        from common.learn import LEARN_RESULT_TEMPLATE

        task["learn_result_template"] = LEARN_RESULT_TEMPLATE

    return task
