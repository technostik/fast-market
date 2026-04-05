from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import click
import yaml

from common.core.config import _resolve_config_path
from common.core.yaml_utils import dump_yaml
from commands.setup import (
    load_config,
    save_config,
    init_task_config,
)
from common.cli.helpers import get_editor
from commands.task.prompts import TOOLS_DOC_TEMPLATES


def create_command_docs_prompts_group() -> click.Group:
    @click.group("command-docs-prompts")
    def command_docs_prompts():
        """Manage command documentation prompt templates.

        Note: For human-friendly editing, use 'prompt setup task edit'
        to edit all task configuration in one place.
        """
        pass

    @command_docs_prompts.command("list")
    def list_command_docs_prompts():
        """List available command docs prompts."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        command_docs = task.get("command_docs", {})
        active = command_docs.get("active", "minimal")
        templates = command_docs.get("templates", {})

        click.echo("Available command docs prompts:")

        marker = "*" if active == "minimal" else " "
        click.echo(f" {marker} minimal (default) - Just command names")

        marker = "*" if active == "full" else " "
        click.echo(f" {marker} full - Verbose with examples")

        for name, tpl in sorted(templates.items()):
            if name in ("minimal", "full"):
                continue
            marker = "*" if active == name else " "
            desc = tpl.get("description", "")
            desc_str = f" - {desc}" if desc else ""
            click.echo(f" {marker} {name}{desc_str}")

    @command_docs_prompts.command("set")
    @click.argument("name")
    def set_command_docs_prompt(name: str):
        """Set active command docs prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        command_docs = task.get("command_docs", {})
        templates = command_docs.get("templates", {})

        if name not in templates:
            click.echo(f"Error: Command docs prompt '{name}' not found", err=True)
            click.echo("Available prompts:", err=True)
            for tname in templates.keys():
                click.echo(f"  - {tname}", err=True)
            sys.exit(1)

        command_docs["active"] = name
        save_config(config_path, config)
        click.echo(f"✓ Active command docs prompt set to: {name}")

    @command_docs_prompts.command("show")
    @click.argument("name")
    def show_command_docs_prompt(name: str):
        """Show a command docs prompt's configuration."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        command_docs = task.get("command_docs", {})
        templates = command_docs.get("templates", {})

        if name not in templates:
            if name in TOOLS_DOC_TEMPLATES:
                click.echo(f"=== {name} (built-in) ===")
                click.echo(f"Template:\n")
                click.echo(TOOLS_DOC_TEMPLATES[name])
            else:
                click.echo(f"Error: Command docs prompt '{name}' not found", err=True)
                sys.exit(1)
            return

        tpl = templates[name]
        click.echo(f"=== {name} ===")
        if tpl.get("description"):
            click.echo(f"Description: {tpl['description']}")
        click.echo(f"\nTemplate:\n")
        click.echo(tpl.get("template", ""))

    @command_docs_prompts.command("add")
    @click.argument("name")
    def add_command_docs_prompt(name: str):
        """Add a new command docs prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        command_docs = task.setdefault("command_docs", {})
        templates = command_docs.setdefault("templates", {})

        if name in templates:
            click.echo(f"Error: Command docs prompt '{name}' already exists", err=True)
            sys.exit(1)

        templates[name] = {
            "description": f"Custom command docs prompt: {name}",
            "template": "{fastmarket_tools_minimal}{system_commands_minimal}{other_commands_minimal}",
        }
        save_config(config_path, config)
        click.echo(f"✓ Added command docs prompt: {name}")

        import subprocess

        editor = get_editor()

        yaml_content = dump_yaml(templates[name])
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            prefix=f"fastmarket-command-docs-{name}-",
            delete=False,
        ) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            subprocess.run([editor, str(temp_path)], check=True)
            new_content = yaml.safe_load(temp_path.read_text())
            if new_content:
                templates[name] = new_content
                save_config(config_path, config)
                click.echo(f"✓ Updated command docs prompt: {name}")
        finally:
            temp_path.unlink(missing_ok=True)

    return command_docs_prompts
