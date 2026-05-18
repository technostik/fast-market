from __future__ import annotations

import click
from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("show")
    @click.option(
        "--cdp-port",
        "-p",
        "cdp_port",
        type=int,
        default=9222,
        show_default=True,
        help="Chrome DevTools Protocol port.",
    )
    @click.option(
        "--width",
        default=1200,
        show_default=True,
        help="Window width when showing.",
    )
    @click.option(
        "--height",
        default=800,
        show_default=True,
        help="Window height when showing.",
    )
    def show_cmd(cdp_port: int, width: int, height: int) -> None:
        """Show the browser window (bring it back on screen)."""
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

            # Get actual windowId
            ws.send(json.dumps({
                "id": 1,
                "method": "Browser.getWindowForTarget",
                "params": {"targetId": target_id}
            }))
            result = json.loads(ws.recv())
            window_id = result.get("result", {}).get("windowId", 1)

            # Move window to visible position
            ws.send(json.dumps({
                "id": 2,
                "method": "Browser.setWindowBounds",
                "params": {
                    "windowId": window_id,
                    "bounds": {"left": 100, "top": 100, "width": width, "height": height}
                }
            }))
            ws.recv()
            ws.close()

            click.echo(f"Browser window shown at {width}x{height}.", err=True)

        except Exception as e:
            raise click.ClickException(f"Failed to show browser: {e}")

    return CommandManifest(
        name="show",
        click_command=show_cmd,
    )
