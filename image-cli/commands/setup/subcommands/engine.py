from __future__ import annotations

import click

from commands.helpers import _configure_logging
from commands.setup.helpers import (
    add_engine,
    get_config_path,
    load_config,
    remove_engine,
    set_default_engine,
    set_model_path,
)


def register(plugin_manifests: dict) -> click.Command:
    group = click.Group(
        "engine", help="Manage image generation engines."
    )

    @group.command("add", help="Add an engine (flux2).")
    @click.option(
        "--engine",
        "-e",
        type=click.Choice(["flux2"]),
        required=True,
        help="Engine to add",
    )
    @click.pass_context
    def add_cmd(ctx, engine, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        add_engine(config_path, load_config(config_path), engine)

    @group.command("remove", help="Remove an engine.")
    @click.argument("engine")
    @click.pass_context
    def remove_cmd(ctx, engine, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        remove_engine(config_path, load_config(config_path), engine)

    @group.command("set-default", help="Set the default engine.")
    @click.argument("engine")
    @click.pass_context
    def set_default_cmd(ctx, engine, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        set_default_engine(config_path, load_config(config_path), engine)

    @group.command("set-model-path", help="Set model path (format: engine:path).")
    @click.argument("engine_path")
    @click.pass_context
    def set_model_path_cmd(ctx, engine_path, **kwargs):
        _configure_logging(ctx.obj["verbose"])
        config_path = get_config_path()
        set_model_path(config_path, load_config(config_path), engine_path)

    return group
