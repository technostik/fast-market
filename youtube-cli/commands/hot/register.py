from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.common.channel_search import (
    search_channels,
    format_channel_entry,
    select_channel_interactive,
)
from common.cli.helpers import out
from common.core.config import (
    load_common_config,
    load_youtube_config,
    load_youtube_channel_list_config,
)
from common.core.paths import get_youtube_channel_list_path
from common.core.yaml_utils import dump_yaml
from common.youtube.utils import extract_video_id
from common.youtube.channel_list import (
    load_channel_list_file,
    save_channel_list_file,
    ChannelListFile,
    ThematicList,
    ChannelEntry,
    create_channel_entry,
    slugify,
)
from core.config import load_config
from core.engine import build_youtube_client

# ─── Channel list file helpers ───────────────────────────────────────────────


def _get_channel_list_path() -> Path:
    """Get the channel list file path from config or default."""
    yt_cfg = load_youtube_config()
    return Path(
        yt_cfg.get("channel_list_path", str(get_youtube_channel_list_path()))
    ).expanduser()


def _load_channel_list() -> ChannelListFile:
    """Load the channel list file."""
    path = _get_channel_list_path()
    return load_channel_list_file(path)


def _save_channel_list(channel_list: ChannelListFile) -> None:
    """Save the channel list file."""
    path = _get_channel_list_path()
    save_channel_list_file(path, channel_list)


def _resolve_output_path(output: str) -> str:
    """Resolve output path to workdir if relative."""
    output_path = Path(output)
    if not output_path.is_absolute():
        common_config = load_common_config()
        workdir = common_config.get("workdir")
        if workdir:
            output_path = Path(workdir).expanduser().resolve() / output
        else:
            output_path = Path.cwd() / output
    return str(output_path)


# ─── Channel search helper ───────────────────────────────────────────────────
def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("hot", invoke_without_command=True)
    @click.pass_context
    def hot_group(ctx):
        """Manage thematic channel lists and fetch hot comments.

        Channels are stored in a YAML file (configurable via youtube.channel_list_path).

        Subcommands:
          add          Add a channel to a thematic list (interactive wizard)
          list         List channels (optionally filtered by theme)
          list-themes  List all thematic lists
          delete       Remove a channel from a list
          assign       Move or duplicate a channel to another theme
          fetch-comment  Fetch new comments from last videos in a thematic list
          fetch-video    Fetch the last video from a thematic list
        """
        if ctx.invoked_subcommand is None:
            click.echo("Usage: youtube hot <command>")
            click.echo("")
            click.echo("Commands:")
            click.echo("  add          Add a channel to a thematic list (wizard)")
            click.echo("  list         List channels (optionally filtered by theme)")
            click.echo("  list-themes  List all thematic lists")
            click.echo("  delete       Remove a channel from a list")
            click.echo("  assign       Move or duplicate a channel to another theme")
            click.echo("  fetch-comment  Fetch new comments from last videos")
            click.echo("  fetch-video    Fetch the last video from a theme")
            click.echo("")
            click.echo("Examples:")
            click.echo("  youtube hot add                    # Interactive wizard")
            click.echo("  youtube hot list tech              # List 'tech' channels")
            click.echo(
                "  youtube hot fetch-comment tech -n 5  # Fetch 5 comments per channel"
            )
            click.echo("  youtube hot fetch-video tech         # Get last video")
            click.echo(
                "  youtube hot assign UC... --theme tech --target ai --duplicate"
            )

    # ─── ADD (wizard) ─────────────────────────────────────────────────────

    @hot_group.command("add")
    @click.option(
        "--theme", "-t", default=None, help="Theme name (will prompt if not given)"
    )
    @click.option(
        "--channel-id", "-c", default=None, help="Channel ID (skips search wizard)"
    )
    @click.option(
        "--name", default=None, help="Channel display name (auto-fetched if not given)"
    )
    def add_cmd(theme: str, channel_id: str, name: str):
        """Add a channel to a thematic list via interactive wizard."""
        channel_list = _load_channel_list()

        # Determine theme
        if not theme:
            # Show existing themes
            themes = channel_list.list_thematic_names()
            if themes:
                click.echo("Existing themes:")
                for i, t in enumerate(themes, 1):
                    thematic = channel_list.get_thematic(t)
                    ch_count = len(thematic.channels) if thematic else 0
                    click.echo(
                        f"  [{i}] {t} ({ch_count} channel{'s' if ch_count != 1 else ''})"
                    )
                click.echo(f"  [{len(themes) + 1}] Create new theme")

                choice = input(
                    f"\nSelect theme (1-{len(themes) + 1}) or type new name: "
                ).strip()
                if not choice:
                    raise click.ClickException("No theme specified.")

                if choice.isdigit():
                    idx = int(choice) - 1
                    if idx < len(themes):
                        theme = themes[idx]
                    else:
                        theme = input("New theme name: ").strip()
                        if not theme:
                            raise click.ClickException("No theme name provided.")
                else:
                    theme = choice
            else:
                theme = input("No themes exist. Create new theme name: ").strip()
                if not theme:
                    raise click.ClickException("No theme name provided.")

        # Determine channel
        if not channel_id:
            query = input("Search for a channel (name/keyword): ").strip()
            if not query:
                raise click.ClickException("No search query provided.")

            max_results = 10
            click.echo(f"\nSearching for channels matching '{query}'...")

            results = search_channels(query, max_results)
            if not results:
                raise click.ClickException("No channels found.")

            click.echo(f"\nFound {len(results)} channels:")
            for i, ch in enumerate(results, 1):
                click.echo(format_channel_entry(ch, i))
                click.echo("")

            choice = input(f"Select channel (1-{len(results)}): ").strip()
            if not choice or not choice.isdigit():
                raise click.ClickException("Invalid selection.")

            idx = int(choice) - 1
            if idx < 0 or idx >= len(results):
                raise click.ClickException("Invalid selection.")

            selected = results[idx]
            channel_id = selected["channel_id"]
            title = selected["title"]
            subscribers = selected.get("subscriber_count", 0)
            description = selected.get("description", "")
        else:
            # Fetch name if not provided
            if not name:
                try:
                    config = load_config()
                    client = build_youtube_client(config)
                    info = client.get_channel_info(channel_id)
                    if info:
                        title = info.title
                        subscribers = info.subscriber_count
                        description = info.description
                    else:
                        title = channel_id
                        subscribers = 0
                        description = ""
                except Exception:
                    title = channel_id
                    subscribers = 0
                    description = ""
            else:
                title = name
                subscribers = 0
                description = ""

        # Create channel entry if not exists
        channel_name = slugify(title)
        channel_entry = channel_list.get_channel_by_name(channel_name)
        if channel_entry is None:
            channel_entry = create_channel_entry(
                channel_id=channel_id,
                title=title,
                name=channel_name,
                subscribers=subscribers,
                description=description,
            )
            # Add to global channels list
            channel_list.channels.append(channel_entry)

        # Add to thematic (just the name)
        channel_list.add_channel_to_thematic(channel_name, theme)
        _save_channel_list(channel_list)

        click.echo(f"\nAdded '{title}' ({channel_id}) to theme '{theme}'.")
        click.echo(f"  Name (slugified): {channel_name}")

    # ─── LIST ─────────────────────────────────────────────────────────────

    @hot_group.command("list")
    @click.argument("theme", required=False)
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
    )
    def list_cmd(theme: str, fmt: str):
        """List channels, optionally filtered by theme."""
        channel_list = _load_channel_list()
        thematics = channel_list.thematics

        if not thematics:
            click.echo(
                "No thematic lists configured. Use 'youtube hot add' to create one."
            )
            return

        target_themes = [theme] if theme else [t.name for t in thematics]

        results = []
        for t_name in target_themes:
            thematic = channel_list.get_thematic(t_name)
            if thematic is None:
                if theme:
                    raise click.ClickException(f"Theme '{theme}' not found.")
                continue

            for ch_name in thematic.channels:
                # Resolve channel entry from global list
                ch_entry = channel_list.get_channel_by_name(ch_name)
                if ch_entry is None:
                    continue  # Skip if channel was removed from global list

                entry = {
                    "theme": t_name,
                    "channel_id": ch_entry.id,
                    "name": ch_entry.name,
                    "title": ch_entry.title,
                    "subscribers": ch_entry.subscribers,
                    "description": ch_entry.description,
                    "date_added": ch_entry.date_added,
                }
                results.append(entry)

        if not results:
            click.echo(f"No channels in theme '{theme}'.")
            return

        if fmt == "text":
            current_theme = None
            for entry in results:
                if entry["theme"] != current_theme:
                    current_theme = entry["theme"]
                    click.echo(f"\n=== {current_theme} ===")

                subs = (
                    f" ({entry['subscribers']:,} subscribers)"
                    if entry["subscribers"] > 0
                    else ""
                )
                click.echo(f"  {entry['title']}{subs} ({entry['channel_id']})")
                click.echo(f"    Name: {entry['name']}")
                if entry.get("description"):
                    desc = (
                        entry["description"][:100] + "..."
                        if len(entry["description"]) > 100
                        else entry["description"]
                    )
                    click.echo(f"    Description: {desc}")
                click.echo(f"    Added: {entry['date_added']}")
            click.echo("")
        else:
            out(results, fmt)

    # ─── LIST-THEMES ──────────────────────────────────────────────────────

    @hot_group.command("list-themes")
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
    )
    def list_themes_cmd(fmt: str):
        """List all thematic lists."""
        channel_list = _load_channel_list()
        thematics = channel_list.thematics

        if not thematics:
            click.echo(
                "No thematic lists configured. Use 'youtube hot add' to create one."
            )
            return

        results = []
        for t in thematics:
            results.append(
                {
                    "theme": t.name,
                    "channel_count": len(t.channels),
                }
            )

        if fmt == "text":
            for entry in results:
                click.echo(
                    f"  {entry['theme']} ({entry['channel_count']} channel{'s' if entry['channel_count'] != 1 else ''})"
                )
            click.echo("")
        else:
            out(results, fmt)

    # ─── DELETE ───────────────────────────────────────────────────────────

    @hot_group.command("delete")
    @click.argument("channel_name")
    @click.option("--theme", "-t", default=None, help="Remove from specific theme only")
    def delete_cmd(channel_name: str, theme: str):
        """Remove a channel from a thematic list.

        CHANNEL_NAME: The slugified channel name.
        """
        channel_list = _load_channel_list()
        thematics = channel_list.thematics

        if not thematics:
            raise click.ClickException("No thematic lists configured.")

        if theme:
            target_themes = [channel_list.get_thematic(theme)]
            if not target_themes[0]:
                raise click.ClickException(f"Theme '{theme}' not found.")
        else:
            target_themes = thematics

        removed_from = []
        for thematic in target_themes:
            if thematic.has_channel(channel_name):
                thematic.remove_channel(channel_name)
                removed_from.append((thematic.name, channel_name))

        if not removed_from:
            raise click.ClickException(
                f"Channel '{channel_name}' not found in {'theme' if theme else 'any theme'}."
            )

        _save_channel_list(channel_list)
        for t, name in removed_from:
            click.echo(f"Removed '{name}' from theme '{t}'.")

    # ─── ASSIGN (move/duplicate) ──────────────────────────────────────────

    @hot_group.command("assign")
    @click.argument("channel_name")
    @click.option("--theme", "-t", required=True, help="Source theme")
    @click.option("--target", required=True, help="Target theme")
    @click.option(
        "--duplicate", is_flag=True, help="Copy instead of move (keep in source)"
    )
    def assign_cmd(channel_name: str, theme: str, target: str, duplicate: bool):
        """Move or duplicate a channel to another thematic list.

        CHANNEL_NAME: The slugified channel name.
        """
        channel_list = _load_channel_list()

        source_thematic = channel_list.get_thematic(theme)
        if not source_thematic:
            raise click.ClickException(f"Source theme '{theme}' not found.")

        if not source_thematic.has_channel(channel_name):
            raise click.ClickException(
                f"Channel '{channel_name}' not found in theme '{theme}'."
            )

        # Verify channel exists in global list
        ch_entry = channel_list.get_channel_by_name(channel_name)
        if not ch_entry:
            raise click.ClickException(
                f"Channel '{channel_name}' not found in channel list."
            )

        # Get or create target theme
        target_thematic = channel_list.get_thematic(target)
        if not target_thematic:
            target_thematic = ThematicList(name=target)
            channel_list.add_thematic(target_thematic)

        # Add to target (just the name)
        target_thematic.add_channel(channel_name)

        # Remove from source unless duplicating
        if not duplicate:
            source_thematic.remove_channel(channel_name)
            # Clean up empty theme
            if not source_thematic.channels:
                channel_list.remove_thematic(theme)
            action = "moved"
        else:
            action = "duplicated"

        _save_channel_list(channel_list)
        click.echo(
            f"{ch_entry.title} ({ch_entry.id}) {action} from '{theme}' to '{target}'."
        )

    # ─── FETCH-COMMENT ────────────────────────────────────────────────────

    @hot_group.command("fetch-comment")
    @click.argument("theme", required=False)
    @click.option(
        "--max-comments",
        "-n",
        type=int,
        default=3,
        help="Max comments per video (default: 3)",
    )
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option("--debug", is_flag=True, help="Show debug information")
    def fetch_comment_cmd(
        theme: str, max_comments: int, fmt: str, output: str, debug: bool
    ):
        """Fetch new comments from the last video of each channel in a theme.

        THEME: Optional thematic name. If not provided, uses default_thematic from config.
        """
        # Resolve theme from argument or config
        if not theme:
            yt_channel_list_cfg = load_youtube_channel_list_config()
            theme = yt_channel_list_cfg.get("default_thematic", "")
            if not theme:
                raise click.ClickException(
                    "No thematic list specified. "
                    "Provide THEME argument or set 'default_thematic' in youtube config."
                )
            if debug:
                click.echo(
                    f"[DEBUG] Using default thematic from config: {theme}", err=True
                )

        channel_list = _load_channel_list()
        thematic = channel_list.get_thematic(theme)

        if thematic is None:
            raise click.ClickException(f"Theme '{theme}' not found.")

        channel_names = thematic.channels
        if not channel_names:
            raise click.ClickException(f"No channels in theme '{theme}'.")

        config = load_config()
        client = build_youtube_client(config)

        all_comments = []

        for ch_name in channel_names:
            # Resolve channel entry from global list
            ch_entry = channel_list.get_channel_by_name(ch_name)
            if ch_entry is None:
                if debug:
                    click.echo(
                        f"[DEBUG] Channel '{ch_name}' not found in global list, skipping",
                        err=True,
                    )
                continue

            ch_id = ch_entry.id
            last_fetch = ch_entry.metadata.get("last_fetch")

            if debug:
                click.echo(
                    f"\n[DEBUG] Processing channel: {ch_entry.title} ({ch_id})",
                    err=True,
                )
                click.echo(f"[DEBUG] Last fetch: {last_fetch}", err=True)

            # Get last video
            try:
                videos = client.get_channel_videos(ch_id, max_results=1)
            except Exception as e:
                click.echo(f"Error fetching videos for {ch_name}: {e}", err=True)
                continue

            if not videos:
                if debug:
                    click.echo(f"[DEBUG] No videos found for {ch_name}", err=True)
                continue

            last_video = videos[0]
            video_id = last_video.video_id
            video_title = last_video.title

            if debug:
                click.echo(f"[DEBUG] Last video: {video_title} ({video_id})", err=True)

            # Fetch comments sorted by time (newest first)
            try:
                comments = client.get_comments(
                    video_id=video_id,
                    max_results=max_comments,
                    order="time",
                )
            except Exception as e:
                click.echo(f"Error fetching comments for {video_title}: {e}", err=True)
                continue

            if not comments:
                if debug:
                    click.echo(f"[DEBUG] No comments on {video_title}", err=True)
                continue

            # Filter by last_fetch timestamp
            new_comments = []
            for comment in comments:
                if last_fetch:
                    try:
                        comment_time = datetime.fromisoformat(
                            comment.published_at.replace("Z", "+00:00")
                        )
                        fetch_time = datetime.fromisoformat(
                            last_fetch.replace("Z", "+00:00")
                        )
                        if comment_time <= fetch_time:
                            if debug:
                                click.echo(
                                    f"[DEBUG] Skipping old comment by {comment.author} ({comment.published_at})",
                                    err=True,
                                )
                            continue
                    except (ValueError, AttributeError):
                        # If we can't parse, include it to be safe
                        pass

                comment_dict = comment.to_dict()
                comment_dict["source_video_id"] = video_id
                comment_dict["source_channel_id"] = ch_id
                comment_dict["source_channel_name"] = ch_entry.title
                new_comments.append(comment_dict)

            if debug:
                click.echo(
                    f"[DEBUG] Found {len(new_comments)} new comments from {ch_entry.title}",
                    err=True,
                )

            all_comments.extend(new_comments)

            # Update last_fetch timestamp for this channel
            ch_entry.metadata["last_fetch"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        _save_channel_list(channel_list)

        # Output
        if output:
            resolved_output = _resolve_output_path(output)
            Path(resolved_output).write_text(
                json.dumps(all_comments, ensure_ascii=False, default=str)
                if fmt == "json"
                else dump_yaml(all_comments)
            )
            click.echo(f"Saved {len(all_comments)} comments to {resolved_output}")
        else:
            out(all_comments, fmt)

    # ─── FETCH-VIDEO ──────────────────────────────────────────────────────

    def _resolve_video_id(raw: str) -> str:
        """Extract video ID from a raw string that may be a full URL or bare ID."""
        import re

        vid = extract_video_id(raw)
        if vid is None:
            if re.match(r"^[A-Za-z0-9_-]{11}$", raw):
                return raw
            raise click.ClickException(
                f"Could not extract video ID from: {raw}\n"
                f"Expected a video ID (e.g. 'BF3Z7J5Jv-U') or a YouTube URL."
            )
        return vid

    def _video_to_output_dict(video) -> dict:
        """Convert a Video object to the standard output dictionary format."""
        return {
            "channel_id": video.channel_id,
            "channel_name": video.channel_title,
            "video_id": video.video_id,
            "title": video.title,
            "description": video.description if hasattr(video, "description") else "",
            "url": video.url
            if hasattr(video, "url")
            else f"https://youtube.com/watch?v={video.video_id}",
            "published_at": video.published_at
            if hasattr(video, "published_at")
            else None,
        }

    def _is_video_input(raw: str) -> bool:
        """Check if the input looks like a YouTube URL or bare video ID."""
        import re

        if not raw:
            return False
        if extract_video_id(raw) is not None:
            return True
        if re.match(r"^[A-Za-z0-9_-]{11}$", raw):
            return True
        return False

    @hot_group.command("fetch-video")
    @click.argument("theme", required=False)
    @click.option("--stdin", is_flag=True, help="Read video ID from stdin")
    @click.option(
        "--format",
        "-f",
        "fmt",
        type=click.Choice(["json", "yaml", "text"]),
        default="text",
    )
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option("--debug", is_flag=True, help="Show debug information")
    def fetch_video_cmd(theme: str, stdin: bool, fmt: str, output: str, debug: bool):
        """Fetch the last video from each channel in a theme, or a specific video by URL/ID.

        THEME: Optional thematic name, video URL, or video ID.
        If a YouTube URL or video ID is provided, fetches that specific video.
        If a thematic name is provided, fetches the last video from each channel in that theme.
        If not provided, uses default_thematic from config.
        """
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
            all_videos = []
            for item in data:
                vid = item.get("video_id") or item.get("id") or item.get("url")
                if not vid:
                    continue
                resolved_vid = _resolve_video_id(vid)
                video = client.get_video_infos(resolved_vid)
                if video:
                    all_videos.append(_video_to_output_dict(video))
            if output:
                resolved_output = _resolve_output_path(output)
                Path(resolved_output).write_text(
                    json.dumps(all_videos, ensure_ascii=False, default=str)
                    if fmt == "json"
                    else dump_yaml(all_videos)
                )
                click.echo(f"Saved {len(all_videos)} videos to {resolved_output}")
            else:
                out(all_videos, fmt)
            return

        raw_input = theme
        if not raw_input:
            yt_channel_list_cfg = load_youtube_channel_list_config()
            raw_input = yt_channel_list_cfg.get("default_thematic", "")
            if not raw_input:
                raise click.ClickException(
                    "No thematic or video specified. "
                    "Provide THEME/URL argument, set 'default_thematic' in config, or use --stdin."
                )
            if debug:
                click.echo(
                    f"[DEBUG] Using default thematic from config: {raw_input}", err=True
                )

        if _is_video_input(raw_input):
            video_id = _resolve_video_id(raw_input)
            if debug:
                click.echo(f"[DEBUG] Fetching specific video: {video_id}", err=True)
            video = client.get_video_infos(video_id)
            if not video:
                raise click.ClickException(f"Video not found: {video_id}")
            all_videos = [_video_to_output_dict(video)]
            if output:
                resolved_output = _resolve_output_path(output)
                Path(resolved_output).write_text(
                    json.dumps(all_videos, ensure_ascii=False, default=str)
                    if fmt == "json"
                    else dump_yaml(all_videos)
                )
                click.echo(f"Saved {len(all_videos)} video to {resolved_output}")
            else:
                out(all_videos, fmt)
            return

        channel_list = _load_channel_list()
        thematic = channel_list.get_thematic(raw_input)

        if thematic is None:
            raise click.ClickException(f"Theme '{raw_input}' not found.")

        channel_names = thematic.channels
        if not channel_names:
            raise click.ClickException(f"No channels in theme '{raw_input}'.")

        all_videos = []

        for ch_name in channel_names:
            ch_entry = channel_list.get_channel_by_name(ch_name)
            if ch_entry is None:
                if debug:
                    click.echo(
                        f"[DEBUG] Channel '{ch_name}' not found in global list, skipping",
                        err=True,
                    )
                continue

            ch_id = ch_entry.id

            if debug:
                click.echo(
                    f"\n[DEBUG] Processing channel: {ch_entry.title} ({ch_id})",
                    err=True,
                )

            try:
                videos = client.get_channel_videos(ch_id, max_results=1)
            except Exception as e:
                click.echo(f"Error fetching videos for {ch_name}: {e}", err=True)
                continue

            if not videos:
                if debug:
                    click.echo(f"[DEBUG] No videos found for {ch_name}", err=True)
                continue

            last_video = videos[0]
            video_data = {
                "channel_id": ch_id,
                "channel_name": ch_entry.title,
                "video_id": last_video.video_id,
                "title": last_video.title,
                "description": last_video.description
                if hasattr(last_video, "description")
                else "",
                "url": f"https://youtube.com/watch?v={last_video.video_id}",
                "published_at": last_video.published_at
                if hasattr(last_video, "published_at")
                else None,
            }

            if debug:
                click.echo(
                    f"[DEBUG] Last video: {video_data['title']} ({video_data['video_id']})",
                    err=True,
                )

            all_videos.append(video_data)

        if output:
            resolved_output = _resolve_output_path(output)
            Path(resolved_output).write_text(
                json.dumps(all_videos, ensure_ascii=False, default=str)
                if fmt == "json"
                else dump_yaml(all_videos)
            )
            click.echo(f"Saved {len(all_videos)} videos to {resolved_output}")
        else:
            out(all_videos, fmt)

    return CommandManifest(
        name="hot",
        click_command=hot_group,
    )
