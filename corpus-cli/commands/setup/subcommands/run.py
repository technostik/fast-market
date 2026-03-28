from __future__ import annotations

import click

from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "run",
        help="Run the interactive setup wizard to configure sources, credentials, and preferences.",
    )
    @click.pass_context
    def run_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        from setup_wizard import run_wizard

        run_wizard()

    return run_cmd
