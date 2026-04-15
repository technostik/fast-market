from __future__ import annotations

import click
from fastapi import APIRouter, HTTPException

from commands.base import CommandManifest
from commands.helpers import out


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command(
        "youtube-stats",
        help="Show YouTube channel video statistics (total, fetched, by privacy, by type).",
    )
    @click.option(
        "--format", "-F", "fmt", type=click.Choice(["json", "text"]), default="text"
    )
    @click.option(
        "--max-videos",
        type=int,
        default=None,
        help="Maximum number of videos to fetch from API (default: all)",
    )
    @click.pass_context
    def youtube_stats_cmd(ctx, fmt, max_videos, **kwargs):
        from common.core.config import load_config
        from common.core.registry import build_plugins
        from pathlib import Path

        config = load_config()
        plugins = build_plugins(config, tool_root=Path(__file__).resolve().parents[2])

        if "youtube" not in plugins:
            raise click.ClickException("YouTube plugin not configured")

        youtube_plugin = plugins["youtube"]

        # Fetch all videos using API
        max_fetch = max_videos or 999999
        all_videos = youtube_plugin.list_items(limit=max_fetch, use_api=True)

        # Count by privacy
        by_privacy: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for item in all_videos:
            privacy = item.metadata.get("privacy_status", "unknown")
            by_privacy[privacy] = by_privacy.get(privacy, 0) + 1

            duration = item.metadata.get("duration_seconds", 0) or 0
            if duration <= 60:
                by_type["short"] = by_type.get("short", 0) + 1
            else:
                by_type["long"] = by_type.get("long", 0) + 1

        total_fetched = len(all_videos)

        # Get channel info for total count
        from common.youtube.client import YouTubeClient

        client = youtube_plugin._get_api_client()
        channel_info = client.get_channel_info(youtube_plugin.channel_id)
        total_videos = channel_info.video_count if channel_info else total_fetched

        result = {
            "channel_id": youtube_plugin.channel_id,
            "total": total_videos,
            "fetched": total_fetched,
            "by_privacy": by_privacy,
            "by_type": by_type,
        }

        if fmt == "text":
            click.echo("youtube stats")
            if total_fetched < total_videos:
                click.echo(
                    f"Warning: Only fetched {total_fetched} public videos out of {total_videos} total. Use --max-videos to fetch more."
                )
            click.echo(f"  total: {total_videos}")
            click.echo(f"  fetched: {total_fetched}")
            click.echo(f"  by_privacy: {by_privacy}")
            click.echo(f"  by_type: {by_type}")
        else:
            out([result], fmt)

    return CommandManifest(
        name="youtube-stats",
        click_command=youtube_stats_cmd,
        api_router=_build_router(),
    )


def _build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/youtube-stats")
    def youtube_stats(max_videos: int = None):
        from common.core.config import load_config
        from common.core.registry import build_plugins
        from pathlib import Path
        from common.youtube.client import YouTubeClient

        config = load_config()
        plugins = build_plugins(config, tool_root=Path(__file__).resolve().parents[2])

        if "youtube" not in plugins:
            raise HTTPException(status_code=400, detail="YouTube plugin not configured")

        youtube_plugin = plugins["youtube"]

        max_fetch = max_videos or 999999
        all_videos = youtube_plugin.list_items(limit=max_fetch, use_api=True)

        by_privacy: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for item in all_videos:
            privacy = item.metadata.get("privacy_status", "unknown")
            by_privacy[privacy] = by_privacy.get(privacy, 0) + 1

            duration = item.metadata.get("duration_seconds", 0) or 0
            if duration <= 60:
                by_type["short"] = by_type.get("short", 0) + 1
            else:
                by_type["long"] = by_type.get("long", 0) + 1

        total_fetched = len(all_videos)

        client = youtube_plugin._get_api_client()
        channel_info = client.get_channel_info(youtube_plugin.channel_id)
        total_videos = channel_info.video_count if channel_info else total_fetched

        return {
            "channel_id": youtube_plugin.channel_id,
            "total": total_videos,
            "fetched": total_fetched,
            "by_privacy": by_privacy,
            "by_type": by_type,
        }

    return router
