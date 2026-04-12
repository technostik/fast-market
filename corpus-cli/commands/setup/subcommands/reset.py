from __future__ import annotations

from pathlib import Path

import click

from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> click.Command:
    @click.command(
        "reset",
        help="Reset corpus config to default values (backs up existing config).",
    )
    @click.pass_context
    def reset_cmd(ctx, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        import yaml as _yaml
        from common.core.yaml_utils import dump_yaml as _dump_yaml
        from common.core.paths import get_tool_config_path

        cfg_path = get_tool_config_path("corpus")
        bak_path = cfg_path.with_suffix(".yaml.bak")

        if cfg_path.exists():
            cfg_path.replace(bak_path)
            click.echo(f"Backed up existing config to {bak_path}")

        default_config = {
            "obsidian": {
                "exclude_dirs": [],
            },
            "embed_batch_size": 32,
            "youtube": {
                "index_non_public": False,
            },
        }

        cfg_path.write_text(_dump_yaml(default_config), encoding="utf-8")
        click.echo(f"Created fresh default config at {cfg_path}")
        click.echo("")
        click.echo("Edit with: corpus setup edit")

    return reset_cmd
