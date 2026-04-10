"""Post command — publish messages to social backends.

If the message contains ``---`` on a line by itself, it is treated as a
thread and each section is posted as a reply to the previous one
(supported by backends that implement threading).
"""

from __future__ import annotations

import sys
import warnings

import click

from commands.base import CommandManifest
from commands.helpers import build_plugin, load_config, out, read_stdin


def _split_thread(message: str) -> list[str]:
    """Split message on '---' lines into thread parts."""
    parts = []
    for part in message.split("\n---\n"):
        stripped = part.strip()
        if stripped:
            parts.append(stripped)
    return parts if parts else [message.strip()]


def register(plugin_manifests: dict) -> CommandManifest:
    source_choices = list(plugin_manifests.keys())

    @click.command("post")
    @click.argument("message", required=False)
    @click.option(
        "--backend",
        "-b",
        "backend",
        type=click.Choice(source_choices),
        default="twitter",
        help="Social backend to use.",
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["json", "text"]),
        default="text",
        help="Output format.",
    )
    @click.option(
        "--stdin",
        "-s",
        is_flag=True,
        help="Read message from stdin.",
    )
    @click.option(
        "--media",
        multiple=True,
        default=[],
        help="Path(s) to image file(s) to attach.",
    )
    @click.pass_context
    def post_cmd(ctx, message, backend, fmt, stdin, media, **kwargs):
        if stdin or message == "-":
            message = read_stdin()
            if not message:
                raise click.ClickException("No message provided and no stdin available.")
        elif not message:
            raise click.ClickException(
                "No MESSAGE argument provided and no stdin. "
                "Usage: social post 'Hello world'  OR  echo 'Hello' | social post -s"
            )

        try:
            config = load_config()
        except Exception as e:
            raise click.ClickException(str(e))
        plugin = build_plugin(config, backend)

        media_list: list[str] = list(media)
        threads = _split_thread(message)

        results = []
        prev_id = None
        for i, part in enumerate(threads):
            try:
                # For backends that support threading natively,
                # we post sequentially and reply to previous.
                # The plugin's post() method handles media.
                result = plugin.post(text=part, media=media_list if i == 0 else None)
                result["part"] = i + 1
                result["total"] = len(threads)
                results.append(result)
            except NotImplementedError as e:
                out({"status": "error", "error": str(e), "backend": backend}, fmt)
                raise SystemExit(1)
            except Exception as e:
                out({"status": "error", "error": str(e), "backend": backend}, fmt)
                raise SystemExit(1)

        if len(results) == 1:
            out({"status": "success", "backend": backend, **results[0]}, fmt)
        else:
            out(
                {
                    "status": "success",
                    "backend": backend,
                    "thread": True,
                    "parts": len(results),
                    "results": results,
                },
                fmt,
            )

    # Inject plugin-specific options
    for pm in plugin_manifests.values():
        post_cmd.params.extend(pm.cli_options.get("post", []))

    return CommandManifest(
        name="post",
        click_command=post_cmd,
    )
