from __future__ import annotations

import click
from commands.base import CommandManifest
from commands.helpers import build_plugin, load_config, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.command("alert")
    @click.argument("message")
    @click.option(
        "--source",
        type=click.Choice(source_choices),
        default="telegram",
        help="Messaging platform to use",
    )
    @click.option(
        "--format",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format",
    )
    @click.pass_context
    def alert_cmd(ctx, message, source, fmt, **kwargs):
        config = load_config()
        plugin = build_plugin(config, source)

        wait = kwargs.get("wait", False)
        timeout = kwargs.get("timeout")
        if timeout is None:
            timeout = config.get("telegram", {}).get("default_timeout", 300)

        try:
            result = plugin.send_alert(message, wait_for_ack=wait, timeout=timeout)
            out(
                {
                    "message_id": result["message_id"],
                    "acknowledged": result["acknowledged"],
                    "status": "success",
                },
                fmt,
            )
        except Exception as e:
            out(
                {
                    "status": "error",
                    "error": str(e),
                },
                fmt,
            )
            raise SystemExit(1)

    for pm in plugin_manifests.values():
        alert_cmd.params.extend(pm.cli_options.get("alert", []))

    return CommandManifest(
        name="alert",
        click_command=alert_cmd,
    )
