from __future__ import annotations

import json
import sys
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
    """Extract video ID from a raw string that may be a full URL or bare ID."""
    vid = extract_video_id(raw)
    if vid is None:
        # Maybe it's already a bare video ID
        import re
        if re.match(r'^[A-Za-z0-9_-]{11}$', raw):
            return raw
        raise click.ClickException(
            f"Could not extract video ID from: {raw}\n"
            f"Expected a video ID (e.g. 'BF3Z7J5Jv-U') or a YouTube URL."
        )
    return vid


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("comments")
    @click.argument("video_id", required=False)
    @click.option("--max-results", "-n", type=int, default=20, help="Maximum comments")
    @click.option(
        "--order",
        type=click.Choice(["relevance", "time"]),
        default="relevance",
        help="Sort order",
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
    @click.option("--stdin", is_flag=True, help="Read video IDs from stdin")
    @click.option(
        "--field", default="video_id", help="JSON field to extract IDs from stdin data"
    )
    @click.pass_context
    def comments_cmd(
        ctx, video_id, max_results, order, fmt, output, stdin, field, **kwargs
    ):
        try:
            config = load_config()
            client = build_youtube_client(config)

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

                all_comments = []
                for item in data:
                    vid = item.get(field) or item.get("id") or item.get("video_id")
                    if not vid:
                        continue
                    resolved_vid = _resolve_video_id(vid)
                    comments = client.get_comments(
                        video_id=resolved_vid,
                        max_results=max_results,
                        order=order,
                    )
                    for c in comments:
                        c_dict = c.to_dict()
                        c_dict["source_video_id"] = resolved_vid
                        all_comments.append(c_dict)

                if output:
                    Path(output).write_text(
                        json.dumps(all_comments, ensure_ascii=False, default=str)
                        if fmt == "json"
                        else dump_yaml(all_comments)
                    )
                    click.echo(f"Saved {len(all_comments)} comments to {output}")
                else:
                    out(all_comments, fmt)
            else:
                if not video_id:
                    click.echo("Video ID required when not using --stdin", err=True)
                    return

                resolved_id = _resolve_video_id(video_id)

                comments = client.get_comments(
                    video_id=resolved_id,
                    max_results=max_results,
                    order=order,
                )
                comments_data = [c.to_dict() for c in comments]

                if output:
                    Path(output).write_text(
                        json.dumps(comments_data, ensure_ascii=False, default=str)
                        if fmt == "json"
                        else dump_yaml(comments_data)
                    )
                    click.echo(f"Saved {len(comments_data)} comments to {output}")
                else:
                    out(comments_data, fmt)

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise

    return CommandManifest(
        name="comments",
        click_command=comments_cmd,
    )
