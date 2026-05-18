from __future__ import annotations

import click
from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("hide")
    @click.option(
        "--cdp-port",
        "-p",
        "cdp_port",
        type=int,
        default=9222,
        show_default=True,
        help="Chrome DevTools Protocol port.",
    )
    def hide_cmd(cdp_port: int) -> None:
        """Hide the browser window (move it off-screen)."""
        import json
        import urllib.request
        import websocket

        try:
            # Get tabs
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

            # Move window off-screen
            ws.send(json.dumps({
                "id": 2,
                "method": "Browser.setWindowBounds",
                "params": {
                    "windowId": window_id,
                    "bounds": {"left": -32000, "top": -32000, "width": 1, "height": 1}
                }
            }))
            ws.recv()
            ws.close()

            click.echo("Browser window hidden (moved off-screen).", err=True)

        except Exception as e:
            raise click.ClickException(f"Failed to hide browser: {e}")

    return CommandManifest(
        name="hide",
        click_command=hide_cmd,
    )
