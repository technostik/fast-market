from __future__ import annotations

import click

from commands.base import CommandManifest
from commands.helpers import _configure_logging


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("serve")
    @click.option("--port", "-p", type=int, default=8000)
    @click.pass_context
    def serve_cmd(ctx, port, **kwargs):
        import uvicorn

        _configure_logging(ctx.obj["verbose"])
        uvicorn.run("api.server:app", host="0.0.0.0", port=port, reload=False)

    return CommandManifest(name="serve", click_command=serve_cmd)
