from __future__ import annotations

import re
import shutil
from pathlib import Path

import click

from commands.base import CommandManifest
from common.core.config import load_youtube_config, load_common_config
from common.last_video import get_last_video, SHORT_THRESHOLD_SECONDS
from common.youtube.utils import extract_video_id


def sanitize_filename(text: str) -> str:
    """Sanitize text for filename matching: replace forbidden chars with underscore."""
    # Replace forbidden filesystem chars with underscore
    forbidden = '<>:"/\\|?*'
    sanitized = text
    for char in forbidden:
        sanitized = sanitized.replace(char, '_')
    # Replace multiple spaces/underscores with single underscore
    sanitized = re.sub(r'[\s_]+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    return sanitized


def get_video_info(video_id: str, cookies: str | None = None) -> dict | None:
    """Get video title and duration using yt-dlp."""
    try:
        import yt_dlp
    except ImportError:
        raise click.ClickException("yt-dlp not installed. Install with: pip install yt-dlp")

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            return {
                "title": info.get("title", ""),
                "duration": info.get("duration", 0),
            }
    except Exception as e:
        raise click.ClickException(f"Failed to get video info: {e}")


def get_mp4_duration(file_path: Path) -> float | None:
    """Get duration of MP4 file using ffprobe."""
    try:
        import subprocess
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(file_path)
        ], capture_output=True, text=True)
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return None


def find_existing_video(lookup_dir: Path, sanitized_title: str, expected_duration: float) -> Path | None:
    """Recursively search for matching video file in lookup directory."""
    if not lookup_dir.exists():
        return None

    for mp4_file in lookup_dir.rglob("*.mp4"):
        # Sanitize filename (remove extension)
        file_stem = mp4_file.stem
        sanitized_file = sanitize_filename(file_stem)

        if sanitized_file == sanitized_title:
            # Check duration to confirm match
            file_duration = get_mp4_duration(mp4_file)
            if file_duration and abs(file_duration - expected_duration) < 5:  # 5 second tolerance
                return mp4_file

    return None


def register(plugin_manifests: dict) -> CommandManifest:
    @click.command("get-video")
    @click.argument("url", required=False)
    @click.option("--last", is_flag=True, help="Get the last video from channel")
    @click.option(
        "--channel-id",
        "-c",
        default=None,
        help="YouTube channel ID (defaults to channel_id in config)",
    )
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
        "--short-threshold",
        type=int,
        default=SHORT_THRESHOLD_SECONDS,
        help=f"Duration threshold in seconds for short detection (default: {SHORT_THRESHOLD_SECONDS}s = 3min)",
    )
    @click.option("--debug", is_flag=True, help="Show debug information")
    @click.option(
        "--lookup-dir",
        type=click.Path(exists=False, path_type=Path),
        help="Directory to search for cached videos (default: from config)",
    )
    @click.option("--output", "-o", type=click.Path(path_type=Path), help="Save video to specific file")
    @click.option(
        "--cookies",
        type=click.Path(exists=True),
        help="Path to cookies file for authenticated requests",
    )
    def get_video_cmd(
        url: str | None,
        last: bool,
        channel_id: str | None,
        short: bool,
        normal: bool,
        offset: int,
        short_threshold: int,
        debug: bool,
        lookup_dir: Path | None,
        output: Path | None,
        cookies: str | None,
    ):
        if not url and not last:
            raise click.ClickException("Either provide a URL or use --last option")

        if url and last:
            raise click.ClickException("Cannot specify both URL and --last option")

        if last:
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

            url = last_video["url"]
            if debug:
                click.echo(f"DEBUG: Using last video URL: {url}", err=True)

        video_id = extract_video_id(url)
        if not video_id:
            raise click.ClickException(f"Invalid YouTube URL: {url}")

        # Get video info
        click.echo("Fetching video information...", err=True)
        video_info = get_video_info(video_id, cookies)
        if not video_info:
            raise click.ClickException("Could not fetch video information")

        title = video_info["title"]
        duration = video_info["duration"]
        sanitized_title = sanitize_filename(title)

        click.echo(f"Video: {title}", err=True)
        click.echo(f"Duration: {duration} seconds", err=True)

        # Determine lookup directory
        if lookup_dir is None:
            yt_config = load_youtube_config()
            default_cache = str(Path.home() / ".cache" / "youtube-videos")
            lookup_dir_str = yt_config.get("video_cache_dir", default_cache)
            # Ensure the config has the default video_cache_dir set
            if "video_cache_dir" not in yt_config:
                from common.core.config import save_youtube_config
                yt_config["video_cache_dir"] = default_cache
                save_youtube_config(yt_config)
            lookup_dir = Path(lookup_dir_str).expanduser()

        click.echo(f"Searching in: {lookup_dir}", err=True)

        # Search for existing video
        existing_file = find_existing_video(lookup_dir, sanitized_title, duration)

        # Determine output path
        if output is None:
            common_cfg = load_common_config()
            workdir = common_cfg.get("workdir")
            if workdir:
                output = Path(workdir) / f"{sanitized_title}.mp4"
            else:
                output = Path.cwd() / f"{sanitized_title}.mp4"
        else:
            output = output.expanduser().resolve()

        if existing_file:
            click.echo(f"Found existing video: {existing_file}", err=True)
            # Copy or link to output
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                output.unlink()
            # Use copy for safety, could use hardlink/symlink
            shutil.copy2(existing_file, output)
            click.echo(f"Copied to: {output}")
            return

        # Download new video
        click.echo("Downloading video...", err=True)
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            import yt_dlp
        except ImportError:
            raise click.ClickException("yt-dlp not installed. Install with: pip install yt-dlp")

        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
            "outtmpl": str(output),
            "quiet": False,
            "no_warnings": False,
        }

        if cookies:
            ydl_opts["cookiefile"] = cookies

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            click.echo(f"Downloaded to: {output}")
        except Exception as e:
            raise click.ClickException(f"Download failed: {e}")

    return CommandManifest(
        name="get-video",
        click_command=get_video_cmd,
    )