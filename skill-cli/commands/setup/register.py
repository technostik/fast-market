from __future__ import annotations

import click

from common.core.config import _resolve_config_path
from common.core.yaml_utils import dump_yaml
from commands.base import CommandManifest
from commands.setup import (
    DEFAULT_EVALUATION_PROMPT,
    DEFAULT_PLAN_PROMPT,
    DEFAULT_PREPARATION_PROMPT,
    DEFAULT_SKILL_FROM_DESCRIPTION_PROMPT,
    init_skill_agent_config,
    save_skill_agent_config,
)
from commands.setup.skill_edit import edit_skill_agent_config


def register(plugin_manifests: dict | None = None):
    @click.group("setup", invoke_without_command=True)
    @click.option("--path", "-p", is_flag=True, help="Show config file path")
    @click.pass_context
    def setup_cmd(ctx, path):
        """Manage skill-specific agent configuration."""
        if path:
            config_path = _resolve_config_path("skill")
            click.echo(config_path)
            ctx.exit()

    @setup_cmd.command("show")
    def show():
        """Show current skill agent config."""
        agent = init_skill_agent_config()
        click.echo(dump_yaml({"agent": agent}, sort_keys=False))

    @setup_cmd.command("edit")
    def edit_cmd():
        """Edit the full configuration file in the default editor."""
        edit_skill_agent_config()

    @setup_cmd.command("path")
    def path_cmd():
        """Print path to skill config file."""
        config_path = _resolve_config_path("skill")
        click.echo(config_path)

    @setup_cmd.group("allowed-commands")
    def allowed_commands():
        """Manage allowed commands whitelist."""
        pass

    @allowed_commands.command("list")
    def list_commands():
        """List whitelisted commands (computed from fastmarket_tools + system_commands)."""
        agent = init_skill_agent_config()
        fastmarket_tools = agent.get("fastmarket_tools", {})
        system_commands = agent.get("system_commands", [])
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
        agent = init_skill_agent_config()
        fastmarket_tools = agent.setdefault("fastmarket_tools", {})
        system_commands = agent.setdefault("system_commands", [])

        known_tools = {"corpus", "image", "message", "youtube"}

        if command_type == "system" or (
            command_type is None and command not in known_tools
        ):
            if command not in system_commands:
                system_commands.append(command)
                save_skill_agent_config(agent)
                click.echo(f"Added to system_commands: {command}")
            else:
                click.echo(f"Already present in system_commands: {command}")
        else:
            if command not in fastmarket_tools:
                fastmarket_tools[command] = {
                    "description": f"User-added {command} tool",
                    "commands": ["run"],
                }
                save_skill_agent_config(agent)
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
        agent = init_skill_agent_config()
        fastmarket_tools = agent.get("fastmarket_tools", {})
        system_commands = agent.get("system_commands", [])

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
            save_skill_agent_config(agent)
            click.echo(f"Removed: {command}")
        else:
            click.echo(f"Not present: {command}")

    @setup_cmd.command("set-max-iterations")
    @click.argument("n", type=int)
    def set_max_iterations(n):
        """Set max iterations."""
        agent = init_skill_agent_config()
        agent["max_iterations"] = n
        save_skill_agent_config(agent)
        click.echo(f"Max iterations set to: {n}")

    @setup_cmd.command("set-timeout")
    @click.argument("n", type=int)
    def set_timeout(n):
        """Set default timeout."""
        agent = init_skill_agent_config()
        agent["default_timeout"] = n
        save_skill_agent_config(agent)
        click.echo(f"Default timeout set to: {n}s")

    @setup_cmd.command("set-workdir")
    @click.argument("path")
    def set_workdir(path):
        """Set default workdir in skill config."""
        from common.core.config import load_tool_config, save_tool_config

        config = load_tool_config("skill")
        config["workdir"] = path
        save_tool_config("skill", config)
        click.echo(f"Default workdir set to: {path}")

    return CommandManifest(name="setup", click_command=setup_cmd)
