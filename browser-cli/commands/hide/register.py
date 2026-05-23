from __future__ import annotations

import os
import shutil
import subprocess

import click
from commands.base import CommandManifest
from commands.helpers import read_browser_state


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("hide")
    @click.option("--cdp-port", "-p", "cdp_port", type=int, default=9222, show_default=True,
                  help="Chrome DevTools Protocol port.")
    def hide_cmd(cdp_port: int) -> None:
        """Minimize the browser window (or minimize Xephyr window if in xephyr mode)."""
        state = read_browser_state()
        mode = state.get("mode", "normal")

        if mode == "xephyr":
            xephyr_pid = state.get("xephyr_pid")
            real_display = state.get("real_display", ":0")
            if not xephyr_pid:
                click.echo("No Xephyr PID in state.", err=True)
                return
            if not shutil.which("xdotool"):
                raise click.ClickException("xdotool not found — install with: sudo apt install xdotool")
            env = {**os.environ, "DISPLAY": real_display}
            result = subprocess.run(
                ["xdotool", "search", "--pid", str(xephyr_pid)],
                capture_output=True, text=True, env=env,
            )
            ids = result.stdout.strip().split()
            if not ids:
                click.echo("Xephyr window not found — may already be minimized.", err=True)
                return
            subprocess.run(["xdotool", "windowminimize", ids[-1]], env=env)
            click.echo("Xephyr window minimized.", err=True)
            return

        if mode == "xvfb":
            click.echo("Browser is on Xvfb — already invisible.", err=True)
            return

        import json
        import urllib.request
        import websocket

        try:
            with urllib.request.urlopen(f"http://localhost:{cdp_port}/json") as resp:
                tabs = json.loads(resp.read())
            if not tabs:
                raise click.ClickException("No browser tabs found")

            target_id = tabs[0]["id"]
            ws_url = tabs[0]["webSocketDebuggerUrl"]
            ws = websocket.create_connection(ws_url, timeout=5)

            ws.send(json.dumps({
                "id": 1,
                "method": "Browser.getWindowForTarget",
                "params": {"targetId": target_id},
            }))
            result = json.loads(ws.recv())
            window_id = result.get("result", {}).get("windowId", 1)

            ws.send(json.dumps({
                "id": 2,
                "method": "Browser.setWindowBounds",
                "params": {
                    "windowId": window_id,
                    "bounds": {"windowState": "minimized"},
                },
            }))
            ws.recv()
            ws.close()

            click.echo("Browser window minimized.", err=True)

        except Exception as e:
            raise click.ClickException(f"Failed to hide browser: {e}")

    return CommandManifest(name="hide", click_command=hide_cmd)
