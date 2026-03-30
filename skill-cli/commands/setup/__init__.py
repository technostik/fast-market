from __future__ import annotations

import yaml

from common.core.config import _resolve_config_path
from common.core.yaml_utils import dump_yaml


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


DEFAULT_AGENT_PROMPT_TEMPLATE = """You are a skill execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

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

DEFAULT_FASTMARKET_TOOLS = {
    "corpus": {
        "description": "Search and query your knowledge base with embeddings.",
        "commands": ["index", "search", "list", "delete"],
    },
    "image": {
        "description": "Generate images from text prompts.",
        "commands": ["generate", "serve", "setup"],
    },
    "message": {
        "description": "Send messages and alerts via Telegram.",
        "commands": ["alert", "ask", "setup"],
    },
    "youtube": {
        "description": "Search YouTube videos and manage comments.",
        "commands": ["search", "comments", "reply", "setup"],
    },
}

DEFAULT_PREPARATION_PROMPT = """You are a skill orchestrator. Before entering the planning loop,
read the goal and available skills, then produce a structured execution plan.

## Goal
{goal}

## Available Skills
{skills_list}

## Your Task

Analyze the goal and available skills. Produce a JSON object with your plan:

```json
{{
  "plan": "step by step description of intended approach",
  "success_criteria": "concrete, observable description of what done looks like",
  "risks": "what could go wrong and how to handle it"
}}
```

Be specific about the order of skills and what each step should accomplish.
"""

DEFAULT_EVALUATION_PROMPT = """You are evaluating whether the last step brought us closer to the goal.

## Goal
{goal}

## Success Criteria
{success_criteria}

## History
{history}

## Last Step Result
{last_summary}

## Your Task

Determine if the last step satisfied the success criteria. Return a JSON object:

```json
{{
  "satisfied": true or false,
  "reason": "one sentence explaining your assessment",
  "suggestion": "if not satisfied, what to try next"
}}
```

Be honest — if the goal isn't met, say so and suggest a different approach."""

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

    if "tools_doc" not in agent_dict:
        agent_dict["tools_doc"] = {
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

    return agent_dict
