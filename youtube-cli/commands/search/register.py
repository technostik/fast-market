from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from common.cli.helpers import out
from common.core.yaml_utils import dump_yaml
from common.youtube.models import Video
from core.config import load_config
from core.engine import build_youtube_client


def _read_stdin() -> list:
    """Read JSON from stdin."""
    if sys.stdin.isatty():
        return []
    try:
        data = json.load(sys.stdin)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        try:
            return yaml.safe_load(sys.stdin)
        except yaml.YAMLError:
            return []


def _read_file(path: str) -> list:
    """Read JSON or YAML from file."""
    content = Path(path).read_text()
    if path.endswith(".yaml") or path.endswith(".yml"):
        return yaml.safe_load(content) or []
    return json.loads(content)


def _search_with_ytdlp(query: str, max_results: int) -> list[dict]:
    """Search using yt-dlp and return Video dicts."""
    if not shutil.which("yt-dlp"):
        raise click.ClickException(
            "yt-dlp not found. Install it with: pip install yt-dlp"
        )

    search_query = f"ytsearch{max_results}:{query}"
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--dump-single-json", search_query],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)

    videos = []
    for entry in data.get("entries", []):
        if not entry:
            continue
        videos.append(
            Video.from_video_list(
                {
                    "id": entry.get("id", ""),
                    "title": entry.get("title", ""),
                    "description": entry.get("description", ""),
                    "channel_id": entry.get("channel_id", ""),
                    "channel_title": entry.get("channel") or entry.get("uploader", ""),
                    "view_count": entry.get("view_count", 0),
                    "url": entry.get("url", ""),
                }
            ).to_dict()
        )
    return videos


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("search")
    @click.argument("keywords", nargs=-1, required=False)
    @click.option("--max-results", "-n", type=int, default=10, help="Maximum results")
    @click.option(
        "--order",
        type=click.Choice(["date", "relevance", "rating", "title", "viewCount"]),
        default="relevance",
        help="Sort order",
    )
    @click.option("--language", default="en", help="Language code (default: en)")
    @click.option("--combine", is_flag=True, help="Use OR for keywords")
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
        help="Output format",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option(
        "--stdin", is_flag=True, help="Read video IDs from stdin for filtering"
    )
    @click.option(
        "--use-yt-dlp",
        is_flag=True,
        help="Use yt-dlp instead of YouTube API for search",
    )
    @click.pass_context
    def search_cmd(
        ctx,
        keywords,
        max_results,
        order,
        language,
        combine,
        fmt,
        output,
        stdin,
        use_yt_dlp,
        **kwargs,
    ):
        try:
            if stdin:
                video_ids = _read_stdin()
                if video_ids and isinstance(video_ids[0], dict):
                    video_ids = [v.get("video_id", v.get("id", "")) for v in video_ids]
                if not video_ids:
                    click.echo("No video IDs provided via stdin", err=True)
                    return
                config = load_config()
                client = build_youtube_client(config)
                videos = []
                for vid in video_ids:
                    if not vid:
                        continue
                    video = client.get_video_infos(vid)
                    if video:
                        videos.append(video.to_dict())
            else:
                if not keywords:
                    click.echo("Keywords required when not using --stdin", err=True)
                    return
                query = " ".join(keywords)
                if use_yt_dlp:
                    videos = _search_with_ytdlp(query, max_results)
                else:
                    config = load_config()
                    client = build_youtube_client(config)
                    videos = client.search_videos(
                        query=query,
                        max_results=max_results,
                        order=order,
                        language=language,
                        combine_keywords=combine,
                    )
                    videos = [v.to_dict() for v in videos]

            if output:
                Path(output).write_text(
                    json.dumps(videos, ensure_ascii=False, default=str)
                    if fmt == "json"
                    else dump_yaml(videos)
                )
                click.echo(f"Saved {len(videos)} videos to {output}")
            else:
                out(videos, fmt)

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise

    return CommandManifest(
        name="search",
        click_command=search_cmd,
    )
