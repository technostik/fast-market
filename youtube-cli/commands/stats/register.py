from __future__ import annotations

import click
from commands.base import CommandManifest
from common.core.config import load_youtube_config
from common.cli.helpers import out
from common.youtube.utils import iso_duration_to_seconds, is_short_video
from core.engine import build_youtube_client


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("stats")
    @click.option(
        "--channel-id",
        "-c",
        default=None,
        help="YouTube channel ID (defaults to channel_id in config)",
    )
    @click.option(
        "--format",
        "-F",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
        help="Output format",
    )
    @click.option(
        "--max-videos",
        "-m",
        type=int,
        default=1000,
        help="Maximum videos to fetch if channel has more than total",
    )
    def stats_cmd(
        channel_id: str,
        fmt: str,
        max_videos: int,
    ):
        if not channel_id:
            yt_config = load_youtube_config()
            channel_id = yt_config.get("channel_id")
            if not channel_id:
                raise click.ClickException(
                    "No channel_id specified. Use --channel-id or set channel_id in config"
                )

        config = load_youtube_config()
        client = build_youtube_client(config)

        channel_info = client.get_channel_info(channel_id)
        if not channel_info:
            raise click.ClickException(f"Channel not found: {channel_id}")

        total_videos = channel_info.video_count
        fetch_limit = min(total_videos, max_videos)

        videos = client.get_channel_videos(channel_id, max_results=fetch_limit)

        public_count = 0
        stats = {
            "total": total_videos,
            "fetched": len(videos),
            "by_privacy": {
                "public": 0,
                "private": 0,
                "unlisted": 0,
            },
            "by_type": {
                "short": 0,
                "long": 0,
            },
        }

        for video in videos:
            privacy = video.privacy_status or "public"
            if privacy == "public":
                public_count += 1
            if privacy in stats["by_privacy"]:
                stats["by_privacy"][privacy] += 1
            else:
                stats["by_privacy"]["unlisted"] += 1

            duration = video.duration or ""
            if is_short_video(duration):
                stats["by_type"]["short"] += 1
            else:
                stats["by_type"]["long"] += 1

        if public_count < total_videos:
            click.echo(
                f"Warning: Only fetched {public_count} public videos out of {total_videos} total. "
                f"Use --max-videos to fetch more.",
                err=True,
            )

        out(stats, fmt)

    return CommandManifest(
        name="stats",
        click_command=stats_cmd,
    )
