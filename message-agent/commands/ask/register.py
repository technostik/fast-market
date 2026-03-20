from __future__ import annotations

import click
from commands.base import CommandManifest
from commands.helpers import build_plugin, load_config, out


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.command("ask")
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
    def ask_cmd(ctx, message, source, fmt, **kwargs):
        config = load_config()
        plugin = build_plugin(config, source)

        timeout = kwargs.get("timeout")
        if timeout is None:
            timeout = config.get("telegram", {}).get("default_timeout", 300)

        message_id = None
        try:
            message_id = plugin.send_message(message)
            response = plugin.wait_for_reply(timeout)
            out(
                {
                    "message_id": message_id,
                    "response": response,
                    "status": "success",
                },
                fmt,
            )
        except TimeoutError as e:
            out(
                {
                    "message_id": message_id,
                    "response": None,
                    "status": "timeout",
                    "error": str(e),
                },
                fmt,
            )
            raise SystemExit(1)
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
        ask_cmd.params.extend(pm.cli_options.get("ask", []))

    return CommandManifest(
        name="ask",
        click_command=ask_cmd,
    )
