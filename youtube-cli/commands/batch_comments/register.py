from __future__ import annotations

import json
from pathlib import Path

import click

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.yaml_utils import dump_yaml
from core.config import load_config
from core.engine import build_youtube_client


def _detect_format_from_filename(filename: str) -> str:
    """Auto-detect output format from file extension."""
    if filename.endswith(".yaml") or filename.endswith(".yml"):
        return "yaml"
    elif filename.endswith(".json"):
        return "json"
    return "text"


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("batch-comments")
    @click.argument("input_file", type=click.Path(exists=True))
    @click.option(
        "--limit",
        "-n",
        type=int,
        default=5,
        help="Maximum comments per video (default: 5)",
    )
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
        default=None,
        help="Output format (auto-detected from file extension if not specified)",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option(
        "--field",
        default="video_id",
        help="JSON field to extract video IDs from input",
    )
    @click.pass_context
    def batch_comments_cmd(ctx, input_file, limit, order, fmt, output, field, **kwargs):
        try:
            config = load_config()
            client = build_youtube_client(config)

            # Read input file
            input_path = Path(input_file)
            try:
                data = json.loads(input_path.read_text())
            except json.JSONDecodeError:
                import yaml

                data = yaml.safe_load(input_path.read_text())

            if not isinstance(data, list):
                data = [data]

            # Extract comments from all videos
            all_comments = []
            for item in data:
                vid = item.get(field) or item.get("id") or item.get("video_id")
                if not vid:
                    continue

                # Build video URL from video_id
                if vid.startswith("http"):
                    video_url = vid
                else:
                    video_url = f"https://www.youtube.com/watch?v={vid}"

                comments = client.get_comments(
                    video_id=vid,
                    max_results=limit,
                    order=order,
                )
                for c in comments:
                    c_dict = c.to_dict()
                    c_dict["video_url"] = video_url
                    all_comments.append(c_dict)

            # Output results
            if output:
                # Auto-detect format from filename if not explicitly specified
                output_fmt = fmt if fmt else _detect_format_from_filename(output)
                
                if output_fmt == "json":
                    Path(output).write_text(
                        json.dumps(all_comments, ensure_ascii=False, default=str)
                    )
                elif output_fmt == "yaml":
                    Path(output).write_text(dump_yaml(all_comments))
                else:
                    # text format - write as JSON lines or simple text
                    Path(output).write_text(
                        json.dumps(all_comments, ensure_ascii=False, default=str)
                    )
                click.echo(f"Saved {len(all_comments)} comments to {output}", err=True)
            else:
                # Default to text if no output file and no format specified
                out(all_comments, fmt if fmt else "text")

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise

    return CommandManifest(
        name="batch-comments",
        click_command=batch_comments_cmd,
    )
