from __future__ import annotations

import click

from commands.helpers import _configure_logging
from commands.setup.helpers import get_config_path, reset_config


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "reset",
        help="Reset image-agent config to defaults (backs up existing config).",
    )
    @click.pass_context
    def reset_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        reset_config(get_config_path())

    return reset_cmd
