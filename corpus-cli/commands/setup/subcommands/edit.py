from __future__ import annotations

import click

from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "edit",
        help="Open the corpus config.yaml file in your default editor.",
    )
    @click.pass_context
    def edit_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        from pathlib import Path as _Path
        from common.core.paths import get_tool_config_path
        from common.cli.helpers import open_editor

        cfg_path = get_tool_config_path("corpus")
        if not cfg_path.exists():
            raise click.ClickException(
                f"Config file not found at {cfg_path} — run 'corpus setup run' first"
            )

        click.echo(f"Opening {cfg_path} in editor...")
        open_editor(cfg_path)

    return edit_cmd
