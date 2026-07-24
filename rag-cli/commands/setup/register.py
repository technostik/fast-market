from __future__ import annotations

import click

from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup")
    def setup_group():
        """RAG tool configuration."""
        pass

    @setup_group.command("run")
    def run_cmd():
        click.echo("Run 'toolsetup' to configure LLM providers for rag-cli.")

    @setup_group.command("wizard")
    def wizard_cmd():
        click.echo("Run 'toolsetup' to configure LLM providers for rag-cli.")

    @setup_group.command("edit")
    def edit_cmd():
        from common.core.paths import get_tool_config_path
        from common.cli.helpers import open_editor

        config_path = get_tool_config_path("rag")
        click.echo(f"Opening {config_path} ...")
        open_editor(config_path)

    return CommandManifest(name="setup", click_command=setup_group)
