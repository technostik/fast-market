from __future__ import annotations

from commands.base import CommandManifest
from core.config import load_config
from core.engine import build_youtube_client
from common.youtube.utils import is_short_video
import click


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("get-last")
    @click.option(
        "--short",
        is_flag=True,
        help="Filter to YouTube Shorts only (duration <= 60s)",
    )
    @click.option(
        "--normal",
        is_flag=True,
        help="Filter to normal videos only (duration > 60s)",
    )
    @click.option(
        "--channel-id",
        "-c",
        help="Override channel ID (defaults to authenticated user's channel)",
    )
    def get_last_cmd(short: bool, normal: bool, channel_id: str | None):
        config = load_config()
        client = build_youtube_client(config)

        if channel_id:
            actual_channel_id = channel_id
        else:
            channel_info = client.get_channel_info("mine")
            if not channel_info:
                raise click.ClickException(
                    "Could not determine authenticated channel. Use --channel-id to specify."
                )
            actual_channel_id = channel_info.channel_id

        videos = client.get_channel_videos(actual_channel_id, max_results=50)

        if not videos:
            raise click.ClickException("No videos found in channel")

        last_video = None
        for video in videos:
            details = client.get_video_details(video.video_id)
            if not details:
                continue
            duration = details.get("duration", "")
            video_is_short = is_short_video(duration)

            if short and video_is_short:
                last_video = video
                break
            elif normal and not video_is_short:
                last_video = video
                break
            elif not short and not normal:
                last_video = video
                break

        if not last_video:
            filter_type = "short" if short else "normal" if normal else "any"
            raise click.ClickException(f"No {filter_type} videos found")

        click.echo(last_video.title)
        click.echo(last_video.url)

    return CommandManifest(
        name="get-last",
        click_command=get_last_cmd,
    )
