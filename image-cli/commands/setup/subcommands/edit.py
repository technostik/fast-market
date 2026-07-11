from __future__ import annotations

import click

from commands.helpers import _configure_logging
from commands.setup.helpers import get_config_path, get_default_config, save_config
from common.cli.helpers import open_editor


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "edit",
        help="Open the image-agent config in your default editor.",
    )
    @click.pass_context
    def edit_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()

        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            save_config(config_path, get_default_config())
            click.echo(f"Created default config at {config_path}")

        click.echo(f"Opening config: {config_path}")
        open_editor(config_path)

    return edit_cmd
