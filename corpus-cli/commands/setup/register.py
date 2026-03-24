from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command(
        "setup",
        help="Run the interactive setup wizard to configure sources, credentials, and preferences.",
    )
    @click.pass_context
    def setup_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        from setup_wizard import run_wizard

        run_wizard()

    return CommandManifest(name="setup", click_command=setup_cmd)
