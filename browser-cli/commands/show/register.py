from __future__ import annotations

import os
import shutil
import subprocess

import click
from commands.base import CommandManifest
from commands.helpers import read_browser_state, take_cdp_screenshot


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("show")
    @click.option("--cdp-port", "-p", "cdp_port", type=int, default=9222, show_default=True,
                  help="Chrome DevTools Protocol port.")
    @click.option("--width", default=1280, show_default=True, help="Window width when restoring.")
    @click.option("--height", default=800, show_default=True, help="Window height when restoring.")
    def show_cmd(cdp_port: int, width: int, height: int) -> None:
        """Restore the browser window. On Xephyr, raises the Xephyr window. On Xvfb, takes a screenshot."""
        state = read_browser_state()
        mode = state.get("mode", "normal")

        if mode == "xephyr":
            xephyr_pid = state.get("xephyr_pid")
            real_display = state.get("real_display", ":0")
            if not xephyr_pid:
                raise click.ClickException("No Xephyr PID in state.")
            if not shutil.which("xdotool"):
                raise click.ClickException("xdotool not found — install with: sudo apt install xdotool")
            env = {**os.environ, "DISPLAY": real_display}
            result = subprocess.run(
                ["xdotool", "search", "--pid", str(xephyr_pid)],
                capture_output=True, text=True, env=env,
            )
            ids = result.stdout.strip().split()
            if not ids:
                raise click.ClickException(f"Could not find Xephyr window (PID {xephyr_pid})")
            subprocess.run(["xdotool", "windowactivate", "--sync", ids[-1]], env=env)
            click.echo("Xephyr window restored.", err=True)
            return

        if mode == "xvfb":
            # Can't bring Xvfb to the real screen — take a screenshot instead
            import tempfile
            out = tempfile.NamedTemporaryFile(suffix=".png", prefix="browser_show_", delete=False)
            out.close()
            try:
                take_cdp_screenshot(cdp_port, out.name)
                click.echo(f"Browser is on Xvfb — screenshot saved to {out.name}", err=True)
                subprocess.Popen(["xdg-open", out.name])
            except Exception as e:
                raise click.ClickException(f"Failed to take screenshot: {e}")
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

            # Restore window to normal state and position
            ws.send(json.dumps({
                "id": 2,
                "method": "Browser.setWindowBounds",
                "params": {
                    "windowId": window_id,
                    "bounds": {
                        "windowState": "normal",
                        "left": 100,
                        "top": 100,
                        "width": width,
                        "height": height,
                    },
                },
            }))
            ws.recv()
            ws.close()

            click.echo(f"Browser window restored ({width}x{height}).", err=True)

        except Exception as e:
            raise click.ClickException(f"Failed to show browser: {e}")

    return CommandManifest(name="show", click_command=show_cmd)
