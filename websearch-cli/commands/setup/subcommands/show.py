from __future__ import annotations

import click

from common.cli.helpers import out
from common.core.config import load_tool_config


def register(plugin_manifests: dict) -> click.Command:
    @click.command("show", help="Print the effective websearch config.")
    def show_cmd():
        config = load_tool_config("websearch")
        out(config, "yaml")

    return show_cmd
