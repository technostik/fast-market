from __future__ import annotations

import click

from core.config import load_config
from core.registry import discover_commands, discover_plugins


@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show logs on stderr.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


def _load() -> None:
    config = load_config()
    plugin_manifests = discover_plugins(config)
    command_manifests = discover_commands(plugin_manifests)
    for command_manifest in command_manifests.values():
        main.add_command(command_manifest.click_command)


_load()

if __name__ == "__main__":
    main()
