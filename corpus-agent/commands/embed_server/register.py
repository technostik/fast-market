from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click
from common import structlog

from commands.base import CommandManifest
from common.core.paths import get_tool_cache_dir

logger = structlog.get_logger(__name__)


def _pid_file() -> Path:
    return get_tool_cache_dir("corpus") / "embedding-server.pid"


def _log_file() -> Path:
    return get_tool_cache_dir("corpus") / "embedding-server.log"


def _read_state() -> tuple[int, int | None, str | None] | None:
    path = _pid_file()
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return (
            int(data["pid"]),
            int(data.get("port")) if data.get("port") else None,
            data.get("model"),
        )
    except Exception:
        try:
            return int(raw), None, None
        except ValueError:
            return None


def _write_state(pid: int, port: int, model: str) -> None:
    _pid_file().write_text(
        json.dumps({"pid": pid, "port": port, "model": model}), encoding="utf-8"
    )


def _is_running() -> tuple[bool, int | None, int | None, str | None]:
    state = _read_state()
    if state is None:
        return False, None, None, None

    pid, port, model = state
    try:
        os.kill(pid, 0)
        return True, pid, port, model
    except ProcessLookupError:
        _pid_file().unlink(missing_ok=True)
        return False, None, None, None


def _health(port: int, timeout: float = 1.5) -> dict | None:
    try:
        import httpx

        resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("embed-server")
    def embed_server_group() -> None:
        """Manage persistent embedding server."""

    @embed_server_group.command("start")
    @click.option("--model", "-m", help="Model name override")
    @click.option("--port", type=int, help="Port override")
    def start_cmd(model: str | None, port: int | None) -> None:
        from common.core.config import load_config

        running, pid, _, _ = _is_running()
        if running:
            click.echo(f"Embedding server already running (PID {pid})")
            return

        config = load_config()
        embeddings_cfg = config.get("embeddings", {})
        if not isinstance(embeddings_cfg, dict):
            embeddings_cfg = {}

        resolved_model = str(
            model
            or embeddings_cfg.get("model", "paraphrase-multilingual-mpnet-base-v2")
        )
        resolved_port = int(port or embeddings_cfg.get("server_port", 8765))

        cmd = [
            sys.executable,
            "-m",
            "core.embedding_server",
            "--model",
            resolved_model,
            "--port",
            str(resolved_port),
        ]
        logger.info(
            "starting_embedding_server", port=resolved_port, model=resolved_model
        )

        log_file = _log_file()
        with log_file.open("ab") as log_handle:
            process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )

        _write_state(process.pid, resolved_port, resolved_model)

        for _ in range(10):
            time.sleep(0.2)
            if _health(resolved_port, timeout=0.2) is not None:
                click.echo(
                    f"Embedding server started in background (PID {process.pid})"
                )
                click.echo("Server health: OK")
                click.echo(f"Server logs: {log_file}")
                return
            if process.poll() is not None:
                _pid_file().unlink(missing_ok=True)
                raise click.ClickException(
                    f"Server process exited early with code {process.returncode}. See logs: {log_file}"
                )

        click.echo(f"Embedding server started in background (PID {process.pid})")
        click.echo("Server health: initializing")
        click.echo(f"Server logs: {log_file}")

    @embed_server_group.command("stop")
    def stop_cmd() -> None:
        running, pid, port, _ = _is_running()
        if not running or pid is None:
            click.echo("Embedding server is not running")
            return

        logger.info("stopping_embedding_server", pid=pid, port=port)

        if port is not None:
            try:
                import httpx

                httpx.post(f"http://127.0.0.1:{port}/shutdown", timeout=2.0)
            except Exception:
                pass
        time.sleep(1)

        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            click.echo("Embedding server forcefully terminated")
        except ProcessLookupError:
            click.echo("Embedding server stopped")
        finally:
            _pid_file().unlink(missing_ok=True)

    @embed_server_group.command("status")
    def status_cmd() -> None:
        from common.core.config import load_config

        config = load_config()
        embeddings_cfg = config.get("embeddings", {})
        if not isinstance(embeddings_cfg, dict):
            embeddings_cfg = {}

        running, pid, port, model = _is_running()
        expected_port = int(embeddings_cfg.get("server_port", 8765))
        expected_model = str(
            embeddings_cfg.get("model", "paraphrase-multilingual-mpnet-base-v2")
        )

        if not running:
            click.echo("Status: NOT RUNNING")
            click.echo(f"Expected model={expected_model} port={expected_port}")
            return

        resolved_port = port or expected_port
        health = _health(resolved_port)
        click.echo(f"Status: RUNNING (PID {pid})")
        click.echo(f"PID file model: {model or expected_model}")
        click.echo(f"Port: {resolved_port}")
        if health is None:
            click.echo("Health: UNREACHABLE")
            return
        click.echo("Health: OK")
        click.echo(f"Server model: {health.get('model')}")
        click.echo(f"Model loaded: {health.get('model_loaded')}")

    @embed_server_group.command("restart")
    @click.option("--model", "-m", help="Model name override")
    @click.option("--port", type=int, help="Port override")
    @click.pass_context
    def restart_cmd(ctx: click.Context, model: str | None, port: int | None) -> None:
        ctx.invoke(stop_cmd)
        time.sleep(1)
        ctx.invoke(start_cmd, model=model, port=port)

    return CommandManifest(name="embed-server", click_command=embed_server_group)
