from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
from pathlib import Path
import webbrowser

import click
import psutil
import uvicorn

from commands.base import CommandManifest
from common import structlog
from common.core.config import load_tool_config
from common.webux.registry import discover_webux_plugins
from core.server import build_app

logger = structlog.get_logger(__name__)


def _kill_process_on_port(port: int) -> None:
    for conn in psutil.net_connections():
        if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
            proc = psutil.Process(conn.pid)
            logger.info("restart_kill", pid=conn.pid, port=port)
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                logger.warning("restart_force_kill", pid=conn.pid)
                proc.kill()
                proc.wait()
            break


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("serve")
    @click.option("--host", default="0.0.0.0")
    @click.option("--port", "-p", default=8007, type=int)
    @click.option("--open", "open_browser", is_flag=True, default=False)
    @click.option("--restart", is_flag=True, default=False, help="Kill existing server on port before starting")
    @click.pass_context
    def serve_cmd(ctx: click.Context, host: str, port: int, open_browser: bool, restart: bool) -> None:
        logging.getLogger().setLevel(
            logging.DEBUG if ctx.obj.get("verbose") else logging.CRITICAL
        )

        if restart:
            _kill_process_on_port(port)

        config = load_tool_config("webux")
        discovered = discover_webux_plugins(config)
        logger.info("server_start", host=host, port=port, plugins=list(discovered.keys()))

        # Ensure all webux prompts exist in the prompt store (idempotent).
        try:
            seed_file = (
                Path(__file__).resolve().parents[2]
                / "webux"
                / "resources"
                / "webux_prompts.yaml"
            )
            subprocess.run(
                ["prompt", "setup", "webux", "import", "--force", "--file", str(seed_file)],
                check=False,
                capture_output=True,
                timeout=60,
            )
        except Exception as exc:  # pragma: no cover - best effort seed
            logger.warning("webux_prompt_seed_failed", error=str(exc))

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
