from __future__ import annotations

import click

from commands.helpers import _configure_logging
from commands.setup.helpers import get_config_path, list_engines, load_config
from common.core.yaml_utils import dump_yaml


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "show",
        help="Show the current image-agent configuration.",
    )
    @click.option("--path", "-p", is_flag=True, help="Only print the config file path")
    @click.option("--engines", "-e", is_flag=True, help="Only list configured engines")
    @click.pass_context
    def show_cmd(ctx, path, engines, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()

        if path:
            click.echo(config_path)
            return

        if not config_path.exists():
            click.echo(f"No config file at {config_path} — run 'image setup wizard'.")

        config = load_config(config_path)

        if engines:
            list_engines(config)
            return

        click.echo(dump_yaml(config, sort_keys=False))

    return show_cmd
