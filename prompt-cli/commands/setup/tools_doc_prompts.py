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


def create_tools_doc_prompts_group() -> click.Group:
    @click.group("tools-doc-prompts")
    def tools_doc_prompts():
        """Manage tools documentation prompt templates.

        Note: For human-friendly editing, use 'prompt setup task edit'
        to edit all task configuration in one place.
        """
        pass

    @tools_doc_prompts.command("list")
    def list_tools_doc_prompts():
        """List available tools doc prompts."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        tools_doc = task.get("tools_doc", {})
        active = tools_doc.get("active", "minimal")
        templates = tools_doc.get("templates", {})

        click.echo("Available tools doc prompts:")

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

    @tools_doc_prompts.command("set")
    @click.argument("name")
    def set_tools_doc_prompt(name: str):
        """Set active tools doc prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        tools_doc = task.get("tools_doc", {})
        templates = tools_doc.get("templates", {})

        if name not in templates:
            click.echo(f"Error: Tools doc prompt '{name}' not found", err=True)
            click.echo("Available prompts:", err=True)
            for tname in templates.keys():
                click.echo(f"  - {tname}", err=True)
            sys.exit(1)

        tools_doc["active"] = name
        save_config(config_path, config)
        click.echo(f"✓ Active tools doc prompt set to: {name}")

    @tools_doc_prompts.command("show")
    @click.argument("name")
    def show_tools_doc_prompt(name: str):
        """Show a tools doc prompt's configuration."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        tools_doc = task.get("tools_doc", {})
        templates = tools_doc.get("templates", {})

        if name not in templates:
            if name in TOOLS_DOC_TEMPLATES:
                click.echo(f"=== {name} (built-in) ===")
                click.echo(f"Template:\n")
                click.echo(TOOLS_DOC_TEMPLATES[name])
            else:
                click.echo(f"Error: Tools doc prompt '{name}' not found", err=True)
                sys.exit(1)
            return

        tpl = templates[name]
        click.echo(f"=== {name} ===")
        if tpl.get("description"):
            click.echo(f"Description: {tpl['description']}")
        click.echo(f"\nTemplate:\n")
        click.echo(tpl.get("template", ""))

    @tools_doc_prompts.command("add")
    @click.argument("name")
    def add_tools_doc_prompt(name: str):
        """Add a new tools doc prompt."""
        config_path = _resolve_config_path("prompt")
        config = load_config(config_path)
        task = init_task_config(config)
        tools_doc = task.setdefault("tools_doc", {})
        templates = tools_doc.setdefault("templates", {})

        if name in templates:
            click.echo(f"Error: Tools doc prompt '{name}' already exists", err=True)
            sys.exit(1)

        templates[name] = {
            "description": f"Custom tools doc prompt: {name}",
            "template": "{fastmarket_tools_minimal}{system_commands_minimal}{other_commands_minimal}",
        }
        save_config(config_path, config)
        click.echo(f"✓ Added tools doc prompt: {name}")

        import subprocess

        editor = get_editor()

        yaml_content = dump_yaml(templates[name])
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            prefix=f"fastmarket-tools-doc-{name}-",
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
                click.echo(f"✓ Updated tools doc prompt: {name}")
        finally:
            temp_path.unlink(missing_ok=True)

    return tools_doc_prompts
