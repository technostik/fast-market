from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import feedparser
import requests
import yt_dlp
import click
from common.core.config import load_youtube_config
from common.youtube.transport import RSSPlaylistTransport

SHORT_THRESHOLD_SECONDS = 180


def _check_rss_available(rss_url: str) -> bool:
    try:
        response = requests.head(rss_url, timeout=5, allow_redirects=True)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _parse_feed_entry(entry) -> dict:
    vid_id = None
    if hasattr(entry, "yt_videoid"):
        vid_id = entry.yt_videoid
    elif hasattr(entry, "id") and "video:" in entry.id:
        vid_id = entry.id.split("video:")[-1]
    elif hasattr(entry, "link"):
        match = re.search(r"v=([a-zA-Z0-9_-]+)", entry.link)
        if match:
            vid_id = match.group(1)

    published = datetime.now(timezone.utc)
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            published = datetime.fromtimestamp(
                time.mktime(entry.published_parsed), tz=timezone.utc
            )
        except (OverflowError, ValueError, TypeError):
            pass

    duration = 0
    if hasattr(entry, "media_content") and entry.media_content:
        try:
            duration = int(entry.media_content[0].get("duration", 0))
        except (ValueError, TypeError):
            pass

    video_url = f"https://youtube.com/watch?v={vid_id}" if vid_id else ""
    if hasattr(entry, "link") and entry.link:
        if "watch?v=" in entry.link:
            video_url = entry.link

    return {
        "id": vid_id,
        "title": entry.get("title", "Untitled"),
        "url": video_url,
        "published": published,
        "duration": duration,
    }


def _fetch_via_yt_dlp(
    channel_id: str, limit: int = 100, debug: bool = False
) -> list[dict]:
    videos_url = f"https://www.youtube.com/channel/{channel_id}/videos"
    shorts_url = f"https://www.youtube.com/channel/{channel_id}/shorts"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "no_color": True,
    }

    def extract_videos(url: str, is_short_playlist: bool = False) -> list[dict]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return []
                entries = info.get("entries", []) or []
                videos = []
                for entry in entries[:limit]:
                    if not entry:
                        continue
                    video_id = entry.get("id")
                    if not video_id:
                        continue

                    upload_date = datetime.now(timezone.utc)
                    if entry.get("upload_date"):
                        try:
                            upload_date = datetime.strptime(
                                entry["upload_date"], "%Y%m%d"
                            ).replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass

                    duration = entry.get("duration") or 0
                    entry_url = entry.get(
                        "url", f"https://www.youtube.com/watch?v={video_id}"
                    )
                    if "/shorts/" not in entry_url and "watch?v=" not in entry_url:
                        entry_url = f"https://www.youtube.com/watch?v={video_id}"
                    is_short = "/shorts/" in entry_url or is_short_playlist
                    if not is_short and 0 < duration < 180:
                        is_short = True

                    videos.append(
                        {
                            "id": video_id,
                            "title": entry.get("title", "Untitled"),
                            "url": entry_url,
                            "published": upload_date,
                            "duration": duration,
                            "is_short": is_short,
                        }
                    )
                return videos
            except Exception as e:
                if debug:
                    click.echo(f"DEBUG: yt-dlp error for {url}: {e}", err=True)
                return []

    all_videos = extract_videos(videos_url) + extract_videos(
        shorts_url, is_short_playlist=True
    )
    all_videos.sort(key=lambda v: v["published"], reverse=True)
    return all_videos[:limit]


def is_short_video(duration: int, threshold: int = SHORT_THRESHOLD_SECONDS) -> bool:
    return duration <= threshold


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
        if offset < 1:
            raise click.ClickException("--offset must be >= 1")

        if not channel_id:
            yt_config = load_youtube_config()
            channel_id = yt_config.get("channel_id")
            if not channel_id:
                raise click.ClickException(
                    "No channel_id specified. Use --channel-id or set channel_id in ~/.config/fast-market/common/youtube/config.yaml"
                )

        if debug:
            click.echo(f"DEBUG: channel_id = {channel_id}", err=True)
            click.echo(f"DEBUG: short_threshold = {short_threshold}s", err=True)

        transport = RSSPlaylistTransport()
        rss_url = transport.get_uploads_playlist(channel_id)

        if debug:
            click.echo(f"DEBUG: RSS URL = {rss_url}", err=True)

        rss_available = _check_rss_available(rss_url)

        videos = []
        use_yt_dlp = False

        if rss_available:
            feed = feedparser.parse(rss_url)

            if hasattr(feed, "bozo_exception") and feed.bozo_exception:
                if debug:
                    click.echo(
                        f"DEBUG: RSS parse error: {feed.bozo_exception}, falling back to yt-dlp",
                        err=True,
                    )
                use_yt_dlp = True
            elif feed.entries:
                for entry in feed.entries:
                    parsed = _parse_feed_entry(entry)
                    if parsed["id"]:
                        videos.append(parsed)
            else:
                use_yt_dlp = True
        else:
            if debug:
                click.echo(
                    "DEBUG: RSS not available (404), falling back to yt-dlp", err=True
                )
            use_yt_dlp = True

        if use_yt_dlp:
            if debug:
                click.echo("DEBUG: fetching via yt-dlp", err=True)
            yt_dlp_videos = _fetch_via_yt_dlp(channel_id, debug=debug)
            for v in yt_dlp_videos:
                videos.append(
                    {
                        "id": v["id"],
                        "title": v["title"],
                        "url": v["url"],
                        "published": v["published"],
                        "duration": v["duration"],
                    }
                )

        if not videos:
            raise click.ClickException("No videos found in channel")

        if debug:
            click.echo(f"DEBUG: got {len(videos)} videos", err=True)

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

        matching = []
        for pos, video in enumerate(videos):
            duration = video["duration"]
            if duration == 0:
                if debug:
                    click.echo(
                        f"DEBUG: {pos + 1}. {video['title'][:40]}... - duration unknown, fetching with yt-dlp",
                        err=True,
                    )
                details = transport.get_video_details([video["id"]])
                detail = details.get(video["id"], {})
                custom = detail.get("_custom", {})
                duration = custom.get("duration_seconds", 0)
                video["duration"] = duration

            video_is_short = is_short_video(duration, short_threshold)

            if filter_short is True and not video_is_short:
                if debug:
                    click.echo(
                        f"DEBUG: {pos + 1}. {video['title'][:40]}... - normal (>{short_threshold}s), skipped (want short)",
                        err=True,
                    )
                continue
            if filter_short is False and video_is_short:
                if debug:
                    click.echo(
                        f"DEBUG: {pos + 1}. {video['title'][:40]}... - short (<={short_threshold}s), skipped (want normal)",
                        err=True,
                    )
                continue

            matching.append((pos, video, video_is_short))
            if debug:
                type_str = "SHORT" if video_is_short else "NORMAL"
                click.echo(
                    f"DEBUG: {pos + 1}. {video['title'][:40]}... - {type_str} - MATCH #{len(matching)}",
                    err=True,
                )

            if offset and len(matching) >= offset:
                if debug:
                    click.echo(
                        f"DEBUG: found {offset} matches, stopping early", err=True
                    )
                break

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

        click.echo(last_video["title"])
        click.echo(last_video["url"])

    from commands.base import CommandManifest

    return CommandManifest(
        name="get-last",
        click_command=get_last_cmd,
    )
