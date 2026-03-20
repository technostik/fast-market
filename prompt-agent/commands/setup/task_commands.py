from __future__ import annotations

import sys

import click

from common.core.config import _resolve_config_path
from commands.setup import load_config, save_config, init_task_config


def create_task_commands_group() -> click.Group:
    @click.group("task-commands")
    def task_commands():
        """Manage task allowed commands."""
        pass

    @task_commands.command("list")
    def list_task_commands():
        """List allowed commands for task execution."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        click.echo("Task configuration:")
        click.echo(f"  Max iterations: {task.get('max_iterations', 20)}")
        click.echo(f"  Default timeout: {task.get('default_timeout', 60)}s")
        click.echo(f"  Allowed commands:")
        for cmd in sorted(task.get("allowed_commands", [])):
            click.echo(f"    - {cmd}")

    @task_commands.command("add")
    @click.argument("command")
    def add_task_command(command: str):
        """Add a command to task whitelist."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        allowed = set(task.get("allowed_commands", []))
        if command in allowed:
            click.echo(f"Command already allowed: {command}")
            return
        allowed.add(command)
        task["allowed_commands"] = sorted(allowed)
        save_config(config_path, config)
        click.echo(f"✓ Added '{command}' to task allowed commands")

    @task_commands.command("remove")
    @click.argument("command")
    def remove_task_command(command: str):
        """Remove a command from task whitelist."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        allowed = set(task.get("allowed_commands", []))
        if command not in allowed:
            click.echo(f"Command not in whitelist: {command}", err=True)
            sys.exit(1)
        allowed.discard(command)
        task["allowed_commands"] = sorted(allowed)
        save_config(config_path, config)
        click.echo(f"✓ Removed '{command}' from task allowed commands")

    return task_commands
