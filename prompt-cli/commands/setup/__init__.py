from __future__ import annotations

from pathlib import Path

import click
import yaml

from common.core.config import _resolve_config_path


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
        yaml.safe_dump(task_data, f, default_flow_style=False, sort_keys=False)


_SUPPORTED_PROVIDERS = {"anthropic", "openai", "openai-compatible", "ollama"}

DEFAULT_FASTMARKET_TOOLS = {
    "corpus": {
        "description": "Search and query your knowledge base with embeddings. Supports file ingestion, semantic search, and YouTube video indexing.",
        "commands": ["index", "search", "list", "delete"],
    },
    "image": {
        "description": "Generate images from text prompts using AI image generation APIs.",
        "commands": ["generate", "serve", "setup"],
    },
    "message": {
        "description": "Send messages and alerts via Telegram. Supports one-way alerts and interactive ask/reply conversations.",
        "commands": ["alert", "ask", "setup"],
    },
    "prompt": {
        "description": "Manage and execute LLM prompt templates with placeholder substitution. Recursive task execution with LLM-driven CLI loop.",
        "commands": [
            "create",
            "apply",
            "alias",
            "task",
            "skill",
            "setup",
            "get",
            "list",
            "edit",
            "delete",
            "logs",
            "providers",
            "show-sys-prompt",
        ],
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

DEFAULT_AGENT_PROMPT_TEMPLATE = """You are a task execution agent. You have access to a sandboxed command-line environment to accomplish tasks.

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

DEFAULT_TOOLS_DOC_FULL_TEMPLATE = "{aliases}{fastmarket_tools}{system_commands}{skills}"

DEFAULT_TOOLS_DOC_MINIMAL_TEMPLATE = (
    "{aliases}"
    "{fastmarket_tools_brief}"
    "{fastmarket_tools_commands}"
    "{system_commands_minimal}"
    "{skills_minimal}"
)


def load_config(config_path: Path) -> dict:
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        config = {}
    if not isinstance(config, dict):
        raise ValueError(f"{config_path.name} must be a mapping")
    providers = config.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("providers must be a mapping")
    return config


def save_config(config_path: Path, config: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def provider_defaults(provider_name: str) -> tuple[str, str, str | None]:
    if provider_name == "anthropic":
        return "claude-sonnet-4-20250514", "ANTHROPIC_API_KEY", None
    if provider_name == "openai":
        return "gpt-4", "OPENAI_API_KEY", None
    if provider_name == "openai-compatible":
        return "gpt-4o-mini", "OPENAI_COMPATIBLE_API_KEY", "https://api.openai.com/v1"
    if provider_name == "ollama":
        return "llama3.2", "", "http://127.0.0.1:11434"
    raise ValueError(f"Unknown provider: {provider_name}")


def require_supported(provider_name: str) -> str:
    normalized = provider_name.lower()
    if normalized not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"Unknown provider: {normalized}")
    return normalized


def build_provider_settings(provider_name: str) -> tuple[dict[str, str], str]:
    default_model, api_key_env, base_url = provider_defaults(provider_name)
    click.echo(f"\n=== Adding {provider_name} provider ===")
    settings = {
        "default_model": click.prompt("Default model", default=default_model),
    }
    if base_url is not None:
        settings["base_url"] = click.prompt("Base URL", default=base_url)
    env_var = ""
    if api_key_env:
        env_var = click.prompt("API key environment variable", default=api_key_env)
        settings["api_key_env"] = env_var
    return settings, env_var


def init_task_config(config: dict) -> dict:
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
                "full": {
                    "description": "Verbose with examples and options",
                    "template": DEFAULT_TOOLS_DOC_FULL_TEMPLATE,
                },
                "minimal": {
                    "description": "Brief with descriptions",
                    "template": DEFAULT_TOOLS_DOC_MINIMAL_TEMPLATE,
                },
            },
        }
    else:
        td = task.get("tools_doc", {})
        templates = td.get("templates", {})
        if "minimal" in templates:
            minimal_tpl = templates["minimal"].get("template", "")
            needs_migration = (
                "{other_commands_minimal}" in minimal_tpl
                or "{fastmarket_tools_minimal}{fastmarket_tools_commands}"
                in minimal_tpl
            )
            if needs_migration:
                templates["minimal"]["template"] = DEFAULT_TOOLS_DOC_MINIMAL_TEMPLATE
                templates["minimal"]["description"] = "Brief with descriptions"
        if "full" in templates:
            full_tpl = templates["full"].get("template", "")
            if "{other_commands}" in full_tpl:
                full_tpl = full_tpl.replace("{other_commands}", "")
                templates["full"]["template"] = full_tpl

    return task


def run_interactive_wizard(config_path: Path, config: dict) -> None:
    click.echo("=== prompt-agent Setup Wizard ===\n")
    if config.get("providers"):
        click.echo("You already have providers configured:")
        for name in config["providers"].keys():
            marker = " (default)" if name == config.get("default_provider") else ""
            click.echo(f"  - {name}{marker}")
        if not click.confirm("\nDo you want to add another provider?", default=False):
            click.echo("\nSetup complete. Use 'prompt setup --help' for more options.")
            return

    click.echo("\nWhich LLM provider do you want to add?")
    click.echo("  1. Anthropic (Claude)")
    click.echo("  2. OpenAI (GPT)")
    click.echo("  3. OpenAI-compatible")
    click.echo("  4. Ollama")
    choice = click.prompt("Enter choice", type=click.Choice(["1", "2", "3", "4"]))
    provider_map = {
        "1": "anthropic",
        "2": "openai",
        "3": "openai-compatible",
        "4": "ollama",
    }
    provider_name = provider_map[choice]
    click.echo(f"\n--- {provider_name} configuration ---")
    settings, env_var = build_provider_settings(provider_name)

    config["providers"][provider_name] = settings
    if not config.get("default_provider"):
        config["default_provider"] = provider_name
    save_config(config_path, config)

    click.echo("\n✓ Setup complete!")
    click.echo(f"\nConfiguration saved to: {config_path}")
    if env_var:
        click.echo("\nDon't forget to set environment variable:")
        click.echo(f"  export {env_var}=your-api-key")
    click.echo("\nYou can add more providers with:")
    click.echo("  prompt setup providers-add <name>")
