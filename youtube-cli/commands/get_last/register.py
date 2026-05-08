from __future__ import annotations

import click
from common.core.config import load_youtube_config
from common.last_video import get_last_video, SHORT_THRESHOLD_SECONDS


def register(plugin_manifests: dict):
    @click.command("get-last")
    @click.option(
        "--short",
        is_flag=True,
        help="Filter to YouTube Shorts only (duration <= 3min, use --short-threshold to override)",
    )
    @click.option(
        "--normal",
        is_flag=True,
        help="Filter to normal videos only (duration > 3min, use --short-threshold to override)",
    )
    @click.option(
        "--offset",
        "-n",
        type=int,
        default=1,
        help="Get the Nth from last (1=last, 2=2nd from last, etc.)",
    )
    @click.option(
        "--channel-id",
        "-c",
        default=None,
        help="YouTube channel ID (defaults to channel_id in common/youtube/config.yaml)",
    )
    @click.option(
        "--short-threshold",
        type=int,
        default=SHORT_THRESHOLD_SECONDS,
        help=f"Duration threshold in seconds for short detection (default: {SHORT_THRESHOLD_SECONDS}s = 3min)",
    )
    @click.option(
        "--debug",
        is_flag=True,
        help="Show debug information",
    )
    def get_last_cmd(
        short: bool,
        normal: bool,
        offset: int,
        channel_id: str,
        short_threshold: int,
        debug: bool,
    ):
        if not channel_id:
            yt_config = load_youtube_config()
            channel_id = yt_config.get("channel_id")
            if not channel_id:
                raise click.ClickException(
                    "No channel_id specified. Use --channel-id or set channel_id in ~/.config/fast-market/common/youtube/config.yaml"
                )

        try:
            last_video = get_last_video(
                channel_id=channel_id,
                short=short,
                normal=normal,
                offset=offset,
                short_threshold=short_threshold,
                debug=debug,
            )
        except ValueError as e:
            raise click.ClickException(str(e))

        click.echo(last_video["title"])
        click.echo(last_video["url"])

    from commands.base import CommandManifest

    return CommandManifest(
        name="get-last",
        click_command=get_last_cmd,
    )
