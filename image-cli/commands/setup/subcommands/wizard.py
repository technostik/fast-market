from __future__ import annotations

import click

from commands.helpers import _configure_logging
from commands.setup.helpers import get_config_path, load_config, run_interactive_wizard


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "wizard",
        help="Run the interactive wizard to configure image-agent settings.",
    )
    @click.pass_context
    def wizard_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        from commands.setup.helpers import get_config_path

        config_path = get_config_path()
        config = load_config(config_path)
        run_interactive_wizard(config_path, config, plugin_manifests)

    return wizard_cmd
