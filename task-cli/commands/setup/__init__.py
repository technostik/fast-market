from __future__ import annotations

from pathlib import Path

import click
import yaml

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


DEFAULT_AGENT_PROMPT_TEMPLATE = """You are a task execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

# Your Task
{task_description}
{params_section}

# Working Directory
All commands execute in: `{workdir}`

You can read and write files in this directory. Relative paths are resolved from here.

---

{command_docs}
{learn_section}

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

DEFAULT_FASTMARKET_TOOLS = {
    "corpus": {
        "description": "Search and query your knowledge base with embeddings.",
        "commands": ["index", "search", "list", "delete"],
    },
    "image": {
        "description": "Generate images from text prompts using AI image generation APIs.",
        "commands": ["generate", "serve", "setup"],
    },
    "message": {
        "description": "Send messages and alerts via Telegram.",
        "commands": ["alert", "ask", "setup"],
    },
    "task": {
        "description": "Execute agentic task",
        "commands": ["run"],
    },
    "skill": {
        "description": "Execute skill scripts",
        "commands": ["list", "run"],
    },
    "youtube": {
        "description": "Search YouTube videos and manage comments via the YouTube Data API.",
        "commands": ["search", "comments", "reply", "setup"],
    },
}

DEFAULT_SYSTEM_COMMANDS = [
    "ls",
    "cat",
    "jq",
    "grep",
    "find",
    "echo",
    "head",
    "tail",
    "wc",
    "mkdir",
    "touch",
    "rm",
    "cp",
    "mv",
    "sort",
    "uniq",
    "awk",
    "sed",
]


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

    if "tools_doc" not in task:
        task["tools_doc"] = {
            "active": "minimal",
            "templates": {
                "minimal": {
                    "description": "Brief with descriptions",
                    "template": "{fastmarket_tools_brief}{system_commands_minimal}",
                },
            },
        }

    if "learn_analysis_prompt" not in task:
        from common.learn import LEARN_ANALYSIS_PROMPT_TEMPLATE

        task["learn_analysis_prompt"] = LEARN_ANALYSIS_PROMPT_TEMPLATE

    if "learn_result_template" not in task:
        from common.learn import LEARN_RESULT_TEMPLATE

        task["learn_result_template"] = LEARN_RESULT_TEMPLATE

    return task
