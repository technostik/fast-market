from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from core.config import load_config
from core.engine import build_youtube_client


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("reply")
    @click.argument("comment_id", required=False)
    @click.argument("text", required=False)
    @click.option(
        "--from-file",
        type=click.Path(exists=True),
        help="JSON/YAML file with array of {comment_id, text}",
    )
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
        help="Output format",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option("--stdin", is_flag=True, help="Read from stdin (JSON array)")
    @click.pass_context
    def reply_cmd(ctx, comment_id, text, from_file, fmt, output, stdin, **kwargs):
        try:
            config = load_config()
            client = build_youtube_client(config)

            replies = []

            if stdin:
                if sys.stdin.isatty():
                    click.echo("No input provided via stdin", err=True)
                    return
                try:
                    data = json.load(sys.stdin)
                except json.JSONDecodeError:
                    data = yaml.safe_load(sys.stdin)

                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    cid = item.get("comment_id") or item.get("id")
                    txt = item.get("text") or item.get("reply")
                    if not cid or not txt:
                        continue
                    result = client.post_comment_reply(cid, txt)
                    if result:
                        replies.append(result.to_dict())
            elif from_file:
                content = Path(from_file).read_text()
                if from_file.endswith(".yaml") or from_file.endswith(".yml"):
                    data = yaml.safe_load(content) or []
                else:
                    data = json.loads(content)

                if not isinstance(data, list):
                    data = [data]

                for item in data:
                    cid = item.get("comment_id") or item.get("id")
                    txt = item.get("text") or item.get("reply")
                    if not cid or not txt:
                        continue
                    result = client.post_comment_reply(cid, txt)
                    if result:
                        replies.append(result.to_dict())
            else:
                if not comment_id or not text:
                    click.echo(
                        "comment_id and text required when not using --from-file or --stdin",
                        err=True,
                    )
                    return

                result = client.post_comment_reply(comment_id, text)
                if result:
                    replies.append(result.to_dict())

            if output:
                Path(output).write_text(
                    json.dumps(replies, ensure_ascii=False, default=str)
                    if fmt == "json"
                    else yaml.dump(
                        replies, allow_unicode=True, default_flow_style=False
                    )
                )
                click.echo(f"Saved {len(replies)} replies to {output}")
            else:
                out(replies, fmt)

        except ValueError as e:
            click.echo(f"Configuration error: {e}", err=True)
            click.echo("Make sure youtube.channel_id is set in config", err=True)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise

    return CommandManifest(
        name="reply",
        click_command=reply_cmd,
    )
