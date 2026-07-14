from __future__ import annotations

import click

from common.core.paths import get_tool_config_path


def register(plugin_manifests: dict) -> click.Command:
    @click.command("path", help="Print the path to the websearch config file.")
    def path_cmd():
        click.echo(str(get_tool_config_path("websearch")))

    return path_cmd
