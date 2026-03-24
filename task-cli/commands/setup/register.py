from __future__ import annotations

import click
import sys
from pathlib import Path

from common.core.config import load_tool_config, save_tool_config
from commands.setup import init_task_config


def register(plugin_manifests: dict | None = None):
    @click.group("setup")
    def setup_cmd():
        """Manage task-specific configuration."""
        pass

    @setup_cmd.command("show")
    def show():
        """Show current apply config."""
        config = load_tool_config("apply")
        if not config:
            click.echo("No apply config found. Run: apply setup")
            return
        task = init_task_config(config)
        import yaml

        click.echo(
            yaml.safe_dump({"apply": task}, default_flow_style=False, sort_keys=False)
        )

    @setup_cmd.group("allowed-commands")
    def allowed_commands():
        """Manage allowed commands whitelist."""
        pass

    @allowed_commands.command("list")
    def list_commands():
        """List whitelisted commands."""
        config = load_tool_config("apply")
        task = init_task_config(config)
        commands = task.get("allowed_commands", [])
        for cmd in commands:
            click.echo(f"  {cmd}")

    @allowed_commands.command("add")
    @click.argument("command")
    def add_command(command):
        """Add command to whitelist."""
        config = load_tool_config("apply")
        task = init_task_config(config)
        commands = task.setdefault("allowed_commands", [])
        if command not in commands:
            commands.append(command)
            save_tool_config("apply", config)
            click.echo(f"Added: {command}")
        else:
            click.echo(f"Already present: {command}")

    @allowed_commands.command("remove")
    @click.argument("command")
    def remove_command(command):
        """Remove command from whitelist."""
        config = load_tool_config("apply")
        task = init_task_config(config)
        commands = task.get("allowed_commands", [])
        if command in commands:
            commands.remove(command)
            save_tool_config("apply", config)
            click.echo(f"Removed: {command}")
        else:
            click.echo(f"Not present: {command}")

    @setup_cmd.command("set-max-iterations")
    @click.argument("n", type=int)
    def set_max_iterations(n):
        """Set max iterations."""
        config = load_tool_config("apply")
        task = init_task_config(config)
        task["max_iterations"] = n
        save_tool_config("apply", config)
        click.echo(f"Max iterations set to: {n}")

    @setup_cmd.command("set-timeout")
    @click.argument("n", type=int)
    def set_timeout(n):
        """Set default timeout."""
        config = load_tool_config("apply")
        task = init_task_config(config)
        task["default_timeout"] = n
        save_tool_config("apply", config)
        click.echo(f"Default timeout set to: {n}s")

    @setup_cmd.command("set-workdir")
    @click.argument("path")
    def set_workdir(path):
        """Set default workdir."""
        config = load_tool_config("apply")
        task = init_task_config(config)
        task["default_workdir"] = path
        save_tool_config("apply", config)
        click.echo(f"Default workdir set to: {path}")

    return setup_cmd
