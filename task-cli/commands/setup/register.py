from __future__ import annotations

import click
import sys
from pathlib import Path

from common.agent.prompts import (
    DEFAULT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_COMMAND_DOCS_TEMPLATES,
    DEFAULT_EVALUATION_PROMPT,
    DEFAULT_PLAN_PROMPT,
    DEFAULT_PREPARATION_PROMPT,
    DEFAULT_SYSTEM_COMMANDS,
    default_fastmarket_tools_dict,
)
from common.core.paths import get_agent_config_path
from common.learn import SKILL_FROM_DESCRIPTION_PROMPT_TEMPLATE
from common.core.yaml_utils import dump_yaml
from commands.setup import init_task_config, load_task_config, save_task_config
from commands.setup.task_edit import edit_task_config


def _default_agent_config() -> dict:
    """Return a fresh default agent config, matching skill-cli's default_skill_agent_config()."""
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


def register(plugin_manifests: dict | None = None):
    @click.group("setup", invoke_without_command=True)
    @click.option("--path", "-p", is_flag=True, help="Show config file path")
    @click.pass_context
    def setup_cmd(ctx, path):
        """Manage task-specific configuration."""
        if path:
            from common.core.config import get_agent_config_path
            config_path = get_agent_config_path()
            click.echo(config_path)
            ctx.exit()

    @setup_cmd.command("show")
    def show():
        """Show current task config."""
        config = load_task_config()
        task = init_task_config(config)
        click.echo(dump_yaml(task, sort_keys=False))

    @setup_cmd.command("edit")
    def edit_cmd():
        """Edit the full configuration file in the default editor."""
        edit_task_config()

    @setup_cmd.group("allowed-commands")
    def allowed_commands():
        """Manage allowed commands whitelist."""
        pass

    @allowed_commands.command("list")
    def list_commands():
        """List whitelisted commands (computed from fastmarket_tools + system_commands)."""
        config = load_task_config()
        task = init_task_config(config)
        fastmarket_tools = task.get("fastmarket_tools", {})
        system_commands = task.get("system_commands", [])
        commands = list(fastmarket_tools.keys()) + system_commands
        for cmd in commands:
            click.echo(f"  {cmd}")

    @allowed_commands.command("add")
    @click.argument("command")
    @click.argument(
        "command_type", required=False, type=click.Choice(["system", "tool"])
    )
    def add_command(command, command_type):
        """Add command to whitelist.

        COMMAND_TYPE can be 'system' (ls, cat, etc.) or 'tool' (corpus, image, etc.).
        If not specified, auto-detects based on known tools.
        """
        config = load_task_config()
        task = init_task_config(config)
        fastmarket_tools = task.setdefault("fastmarket_tools", {})
        system_commands = task.setdefault("system_commands", [])

        known_tools = {"corpus", "image", "message", "task", "youtube"}

        if command_type == "system" or (
            command_type is None and command not in known_tools
        ):
            if command not in system_commands:
                system_commands.append(command)
                save_task_config(task)
                click.echo(f"Added to system_commands: {command}")
            else:
                click.echo(f"Already present in system_commands: {command}")
        else:
            if command not in fastmarket_tools:
                fastmarket_tools[command] = {
                    "description": f"User-added {command} tool",
                    "commands": ["run"],
                }
                save_task_config(task)
                click.echo(f"Added to fastmarket_tools: {command}")
            else:
                click.echo(f"Already present in fastmarket_tools: {command}")

    @allowed_commands.command("remove")
    @click.argument("command")
    @click.argument(
        "command_type", required=False, type=click.Choice(["system", "tool"])
    )
    def remove_command(command, command_type):
        """Remove command from whitelist.

        COMMAND_TYPE can be 'system' (ls, cat, etc.) or 'tool' (corpus, image, etc.).
        If not specified, searches both and removes from wherever found.
        """
        config = load_task_config()
        task = init_task_config(config)
        fastmarket_tools = task.get("fastmarket_tools", {})
        system_commands = task.get("system_commands", [])

        removed = False
        if command_type == "system" or command_type is None:
            if command in system_commands:
                system_commands.remove(command)
                removed = True
        if command_type == "tool" or command_type is None:
            if command in fastmarket_tools:
                del fastmarket_tools[command]
                removed = True

        if removed:
            save_task_config(task)
            click.echo(f"Removed: {command}")
        else:
            click.echo(f"Not present: {command}")

    @setup_cmd.command("set-max-iterations")
    @click.argument("n", type=int)
    def set_max_iterations(n):
        """Set max iterations."""
        config = load_task_config()
        task = init_task_config(config)
        task["max_iterations"] = n
        save_task_config(task)
        click.echo(f"Max iterations set to: {n}")

    @setup_cmd.command("set-timeout")
    @click.argument("n", type=int)
    def set_timeout(n):
        """Set default timeout."""
        config = load_task_config()
        task = init_task_config(config)
        task["default_timeout"] = n
        save_task_config(task)
        click.echo(f"Default timeout set to: {n}s")

    @setup_cmd.command("set-workdir")
    @click.argument("path")
    def set_workdir(path):
        """Set default workdir."""
        config = load_task_config()
        task = init_task_config(config)
        task["default_workdir"] = path
        save_task_config(task)
        click.echo(f"Default workdir set to: {path}")

    @setup_cmd.command("reset")
    @click.option("--agent", "reset_agent", is_flag=True, help="Reset the shared agent config to defaults")
    def reset_cmd(reset_agent):
        """Reset the shared agent config to defaults.

        The agent config is shared with skill at ~/.config/fast-market/common/agent/config.yaml.
        Use task setup edit to modify it.
        """
        _reset_agent_config()
        click.echo("Agent configuration reset to defaults.")

    return setup_cmd


def _reset_agent_config() -> None:
    """Reset the shared agent config to defaults."""
    default_config = _default_agent_config()
    agent_config_path = get_agent_config_path()
    agent_config_path.parent.mkdir(parents=True, exist_ok=True)
    agent_config_path.write_text(
        dump_yaml(default_config, sort_keys=False),
        encoding="utf-8",
    )
