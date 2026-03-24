from __future__ import annotations

from commands.base import CommandManifest
from core.config import load_config
from core.engine import build_youtube_client
from common.youtube.utils import iso_duration_to_seconds
import click

SHORT_THRESHOLD_SECONDS = 180  # 3 minutes


def is_short_video(duration: str, threshold: int = SHORT_THRESHOLD_SECONDS) -> bool:
    """Determine if a video is a YouTube Short based on duration."""
    total_seconds = iso_duration_to_seconds(duration)
    return total_seconds <= threshold


def register(plugin_manifests: dict) -> CommandManifest:
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
        help="Override channel ID (defaults to authenticated user's channel)",
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
        channel_id: str | None,
        short_threshold: int,
        debug: bool,
    ):
        if offset < 1:
            raise click.ClickException("--offset must be >= 1")

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

        if debug:
            click.echo(f"DEBUG: channel_id = {actual_channel_id}", err=True)
            click.echo(f"DEBUG: short_threshold = {short_threshold}s", err=True)

        videos = client.get_channel_videos(actual_channel_id, max_results=100)

        if not videos:
            raise click.ClickException("No videos found in channel")

        if debug:
            click.echo(
                f"DEBUG: got {len(videos)} videos with duration data (batch API call)",
                err=True,
            )

        # Determine filter type: None=all, True=shorts, False=normals
        filter_short = None
        if short and not normal:
            filter_short = True
        elif normal and not short:
            filter_short = False

        if debug:
            filter_name = (
                "short"
                if filter_short is True
                else "normal"
                if filter_short is False
                else "all"
            )
            click.echo(f"DEBUG: filter = {filter_name}, offset = {offset}", err=True)

        # Build list of (position, video, is_short) for matching videos
        # Duration is already fetched in get_channel_videos (batch call)
        matching: list[tuple[int, object, bool]] = []
        for pos, video in enumerate(videos):
            duration = video.duration
            video_is_short = is_short_video(duration, short_threshold)

            # Apply filter
            if filter_short is True and not video_is_short:
                if debug:
                    click.echo(
                        f"DEBUG: {pos + 1}. {video.title[:40]}... - normal (>{short_threshold}s), skipped (want short)",
                        err=True,
                    )
                continue
            if filter_short is False and video_is_short:
                if debug:
                    click.echo(
                        f"DEBUG: {pos + 1}. {video.title[:40]}... - short (<={short_threshold}s), skipped (want normal)",
                        err=True,
                    )
                continue

            matching.append((pos, video, video_is_short))
            if debug:
                type_str = "SHORT" if video_is_short else "NORMAL"
                click.echo(
                    f"DEBUG: {pos + 1}. {video.title[:40]}... - {type_str} - MATCH #{len(matching)}",
                    err=True,
                )

        if debug:
            click.echo(f"DEBUG: total matching: {len(matching)}", err=True)

        if not matching:
            filter_name = (
                "short"
                if filter_short is True
                else "normal"
                if filter_short is False
                else "any"
            )
            raise click.ClickException(f"No {filter_name} videos found")

        # Pick the Nth from last
        target_idx = offset - 1
        if target_idx >= len(matching):
            raise click.ClickException(
                f"Only {len(matching)} {'short' if filter_short is True else 'normal' if filter_short is False else ''} videos found, cannot get offset {offset}"
            )

        if debug:
            click.echo(
                f"DEBUG: selecting match #{offset} (index {target_idx} in matching list)",
                err=True,
            )

        _, last_video, _ = matching[target_idx]

        click.echo(last_video.title)
        click.echo(last_video.url)

    return CommandManifest(
        name="get-last",
        click_command=get_last_cmd,
    )
