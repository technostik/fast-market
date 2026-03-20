from __future__ import annotations

import sys

import click

from common.core.config import _resolve_config_path
from commands.setup import load_config, save_config, init_task_config


def create_task_group() -> click.Group:
    @click.group("task")
    def task():
        """Configure task execution settings."""
        pass

    @task.command("set-max-iterations")
    @click.argument("max_iter", type=int)
    def set_max_iterations(max_iter: int):
        """Set max iterations for task."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        if max_iter < 1:
            click.echo("Max iterations must be at least 1", err=True)
            sys.exit(1)
        task = init_task_config(config)
        task["max_iterations"] = max_iter
        save_config(config_path, config)
        click.echo(f"✓ Set task max iterations to {max_iter}")

    @task.command("set-timeout")
    @click.argument("timeout", type=int)
    def set_timeout(timeout: int):
        """Set default timeout for task commands."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        if timeout < 1:
            click.echo("Timeout must be at least 1 second", err=True)
            sys.exit(1)
        task = init_task_config(config)
        task["default_timeout"] = timeout
        save_config(config_path, config)
        click.echo(f"✓ Set task default timeout to {timeout}s")

    return task
