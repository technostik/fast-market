from __future__ import annotations

import json
import re
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.yaml_utils import dump_yaml
from common.youtube.utils import extract_video_id
from core.config import load_config
from core.engine import build_youtube_client


def _resolve_video_id(raw: str) -> str:
    """Extract video ID from a full URL or accept a bare 11-char ID."""
    vid = extract_video_id(raw)
    if vid:
        return vid
    if re.match(r"^[A-Za-z0-9_-]{11}$", raw):
        return raw
    raise click.ClickException(
        f"Could not extract video ID from: {raw}\n"
        f"Expected a video ID (e.g. 'BF3Z7J5Jv-U') or a YouTube URL."
    )


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("comment-post")
    @click.argument("video", required=True)
    @click.option("--text", default=None, help="Comment text to post")
    @click.option(
        "--text-file",
        type=click.Path(exists=True),
        default=None,
        help="Read comment text from a file (for multiline comments)",
    )
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
        help="Output format",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save result to file")
    @click.pass_context
    def comment_post_cmd(ctx, video, text, text_file, fmt, output, **kwargs):
        try:
            if text_file:
                text_from_file = Path(text_file).read_text(encoding="utf-8").strip()
                if text and text.strip() and text_from_file != text.strip():
                    raise click.ClickException(
                        "Provide either --text or --text-file, not both with different content."
                    )
                text = text_from_file
            if not text or not text.strip():
                raise click.ClickException(
                    "Comment text is required (--text or --text-file)."
                )
            text = text.strip()

            config = load_config()
            client = build_youtube_client(config)

            video_id = _resolve_video_id(video)
            result = client.post_comment(video_id, text)
            if not result:
                raise click.ClickException("API returned no result.")

            payload = result.to_dict()
            payload["comment_url"] = (
                f"https://www.youtube.com/watch?v={video_id}&lc={result.id}"
            )

            if output:
                Path(output).write_text(
                    json.dumps(payload, ensure_ascii=False, default=str)
                    if fmt == "json"
                    else dump_yaml(payload)
                )
                click.echo(f"Saved comment result to {output}")
            else:
                out(payload, fmt)

        except ValueError as e:
            click.echo(f"Configuration error: {e}", err=True)
            click.echo("Make sure youtube.channel_id is set in config", err=True)
            raise
        except Exception as e:
            if not isinstance(e, click.ClickException):
                click.echo(f"Error: {e}", err=True)
            raise

    return CommandManifest(
        name="comment-post",
        click_command=comment_post_cmd,
    )
