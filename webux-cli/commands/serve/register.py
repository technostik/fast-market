from __future__ import annotations

import logging
import os
import signal
import threading
import webbrowser

import click
import uvicorn

from commands.base import CommandManifest
from common import structlog
from common.core.config import load_tool_config
from common.webux.registry import discover_webux_plugins
from core.server import build_app

logger = structlog.get_logger(__name__)
def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("serve")
    @click.option("--host", default="localhost")
    @click.option("--port", "-p", default=8007, type=int)
    @click.option("--open", "open_browser", is_flag=True, default=False)
    @click.pass_context
    def serve_cmd(ctx: click.Context, host: str, port: int, open_browser: bool) -> None:
        logging.getLogger().setLevel(
            logging.DEBUG if ctx.obj.get("verbose") else logging.CRITICAL
        )

        config = load_tool_config("webux")
        discovered = discover_webux_plugins(config)
        logger.info("server_start", host=host, port=port, plugins=list(discovered.keys()))

        if open_browser:
            webbrowser.open(f"http://{host}:{port}")

        def _shutdown() -> None:
            threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()

        app = build_app(
            config=config,
            plugins=discovered,
            shutdown_callback=_shutdown,
        )
        uvicorn.run(app, host=host, port=port)

    return CommandManifest(name="serve", click_command=serve_cmd)
