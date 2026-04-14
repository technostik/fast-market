from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from commands.base import CommandManifest
from commands.common.channel_search import search_channels, format_channel_entry, select_channel_interactive
from common.cli.helpers import out
from common.core.yaml_utils import dump_yaml
from core.config import load_config
from core.engine import build_youtube_client

# ─── State file management ───────────────────────────────────────────────────

_STATE_FILE = Path(
    "~/.config/fast-market/youtube/hot_lists.yaml"
).expanduser()


def _load_state() -> dict:
    """Load the hot lists state from YAML."""
    if not _STATE_FILE.exists():
        return {"lists": {}}
    try:
        data = yaml.safe_load(_STATE_FILE.read_text(encoding="utf-8"))
        if data is None:
            return {"lists": {}}
        return data
    except yaml.YAMLError as exc:
        raise click.ClickException(f"Invalid YAML in {_STATE_FILE}: {exc}") from exc


def _save_state(state: dict) -> None:
    """Save the hot lists state to YAML."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        dump_yaml(state, sort_keys=False),
        encoding="utf-8",
    )


# ─── Channel search helper ───────────────────────────────────────────────────
def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("hot", invoke_without_command=True)
    @click.pass_context
    def hot_group(ctx):
        """Manage thematic channel lists and fetch hot comments.

        Subcommands:
          add          Add a channel to a thematic list (interactive wizard)
          list         List channels (optionally filtered by theme)
          list-themes  List all thematic lists
          delete       Remove a channel from a list
          assign       Move or duplicate a channel to another theme
          fetch        Fetch new comments from last videos in a thematic list
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
            click.echo("  fetch        Fetch new comments from last videos")
            click.echo("")
            click.echo("Examples:")
            click.echo("  youtube hot add                    # Interactive wizard")
            click.echo("  youtube hot list tech              # List 'tech' channels")
            click.echo("  youtube hot fetch tech -n 5        # Fetch 5 comments per channel")
            click.echo("  youtube hot assign UC... --theme tech --target ai --duplicate")

    # ─── ADD (wizard) ─────────────────────────────────────────────────────

    @hot_group.command("add")
    @click.option("--theme", "-t", default=None, help="Theme name (will prompt if not given)")
    @click.option("--channel-id", "-c", default=None, help="Channel ID (skips search wizard)")
    @click.option("--name", default=None, help="Channel display name (auto-fetched if not given)")
    def add_cmd(theme: str, channel_id: str, name: str):
        """Add a channel to a thematic list via interactive wizard."""
        state = _load_state()

        # Determine theme
        if not theme:
            # Show existing themes
            themes = list(state.get("lists", {}).keys())
            if themes:
                click.echo("Existing themes:")
                for i, t in enumerate(themes, 1):
                    ch_count = len(state["lists"][t].get("channels", {}))
                    click.echo(f"  [{i}] {t} ({ch_count} channel{'s' if ch_count != 1 else ''})")
                click.echo(f"  [{len(themes) + 1}] Create new theme")

                choice = input(f"\nSelect theme (1-{len(themes) + 1}) or type new name: ").strip()
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
            name = selected["title"]
        else:
            # Fetch name if not provided
            if not name:
                try:
                    config = load_config()
                    client = build_youtube_client(config)
                    info = client.get_channel_info(channel_id)
                    if info:
                        name = info.title
                    else:
                        name = channel_id
                except Exception:
                    name = channel_id

        # Initialize theme if needed
        if "lists" not in state:
            state["lists"] = {}
        if theme not in state["lists"]:
            state["lists"][theme] = {"channels": {}}

        # Add channel
        theme_data = state["lists"][theme]
        if "channels" not in theme_data:
            theme_data["channels"] = {}

        theme_data["channels"][channel_id] = {
            "name": name,
            "last_fetch": None,
        }

        _save_state(state)
        click.echo(f"\nAdded '{name}' ({channel_id}) to theme '{theme}'.")

    # ─── LIST ─────────────────────────────────────────────────────────────

    @hot_group.command("list")
    @click.argument("theme", required=False)
    @click.option("--format", "-f", "fmt", type=click.Choice(["json", "yaml", "text"]), default="text")
    def list_cmd(theme: str, fmt: str):
        """List channels, optionally filtered by theme."""
        state = _load_state()
        themes = state.get("lists", {})

        if not themes:
            click.echo("No thematic lists configured. Use 'youtube hot add' to create one.")
            return

        target_themes = [theme] if theme else sorted(themes.keys())

        results = []
        for t in target_themes:
            if t not in themes:
                if theme:
                    raise click.ClickException(f"Theme '{theme}' not found.")
                continue

            theme_data = themes[t]
            channels = theme_data.get("channels", {})

            for ch_id, ch_info in channels.items():
                entry = {
                    "theme": t,
                    "channel_id": ch_id,
                    "name": ch_info.get("name", "Unknown"),
                    "last_fetch": ch_info.get("last_fetch"),
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

                last_fetch = entry["last_fetch"] or "never"
                click.echo(f"  {entry['name']} ({entry['channel_id']})")
                click.echo(f"    Last fetch: {last_fetch}")
            click.echo("")
        else:
            out(results, fmt)

    # ─── LIST-THEMES ──────────────────────────────────────────────────────

    @hot_group.command("list-themes")
    @click.option("--format", "-f", "fmt", type=click.Choice(["json", "yaml", "text"]), default="text")
    def list_themes_cmd(fmt: str):
        """List all thematic lists."""
        state = _load_state()
        themes = state.get("lists", {})

        if not themes:
            click.echo("No thematic lists configured. Use 'youtube hot add' to create one.")
            return

        results = []
        for t in sorted(themes.keys()):
            channels = themes[t].get("channels", {})
            results.append({
                "theme": t,
                "channel_count": len(channels),
            })

        if fmt == "text":
            for entry in results:
                click.echo(f"  {entry['theme']} ({entry['channel_count']} channel{'s' if entry['channel_count'] != 1 else ''})")
            click.echo("")
        else:
            out(results, fmt)

    # ─── DELETE ───────────────────────────────────────────────────────────

    @hot_group.command("delete")
    @click.argument("channel_id")
    @click.option("--theme", "-t", default=None, help="Remove from specific theme only")
    def delete_cmd(channel_id: str, theme: str):
        """Remove a channel from a thematic list."""
        state = _load_state()
        themes = state.get("lists", {})

        if not themes:
            raise click.ClickException("No thematic lists configured.")

        if theme:
            if theme not in themes:
                raise click.ClickException(f"Theme '{theme}' not found.")
            target_themes = [theme]
        else:
            target_themes = sorted(themes.keys())

        removed_from = []
        for t in target_themes:
            channels = themes[t].get("channels", {})
            if channel_id in channels:
                ch_name = channels[channel_id].get("name", channel_id)
                del channels[channel_id]
                removed_from.append((t, ch_name))

        if not removed_from:
            raise click.ClickException(
                f"Channel '{channel_id}' not found in {'theme' if theme else 'any theme'}."
            )

        _save_state(state)
        for t, name in removed_from:
            click.echo(f"Removed '{name}' ({channel_id}) from theme '{t}'.")

    # ─── ASSIGN (move/duplicate) ──────────────────────────────────────────

    @hot_group.command("assign")
    @click.argument("channel_id")
    @click.option("--theme", "-t", required=True, help="Source theme")
    @click.option("--target", required=True, help="Target theme")
    @click.option("--duplicate", is_flag=True, help="Copy instead of move (keep in source)")
    def assign_cmd(channel_id: str, theme: str, target: str, duplicate: bool):
        """Move or duplicate a channel to another thematic list."""
        state = _load_state()
        themes = state.get("lists", {})

        if theme not in themes:
            raise click.ClickException(f"Source theme '{theme}' not found.")
        if channel_id not in themes[theme].get("channels", {}):
            raise click.ClickException(f"Channel '{channel_id}' not found in theme '{theme}'.")

        ch_info = themes[theme]["channels"][channel_id]

        # Initialize target theme if needed
        if target not in themes:
            themes[target] = {"channels": {}}
        if "channels" not in themes[target]:
            themes[target]["channels"] = {}

        # Add to target (preserve last_fetch)
        themes[target]["channels"][channel_id] = dict(ch_info)

        # Remove from source unless duplicating
        if not duplicate:
            del themes[theme]["channels"][channel_id]
            # Clean up empty theme
            if not themes[theme]["channels"]:
                del themes[theme]
            action = "moved"
        else:
            action = "duplicated"

        _save_state(state)
        click.echo(
            f"{ch_info['name']} ({channel_id}) {action} from '{theme}' to '{target}'."
        )

    # ─── FETCH ────────────────────────────────────────────────────────────

    @hot_group.command("fetch")
    @click.argument("theme", required=True)
    @click.option("--max-comments", "-n", type=int, default=3, help="Max comments per video (default: 3)")
    @click.option("--format", "-f", "fmt", type=click.Choice(["json", "yaml", "text"]), default="text")
    @click.option("--output", "-o", type=click.Path(), help="Save to file")
    @click.option("--debug", is_flag=True, help="Show debug information")
    def fetch_cmd(theme: str, max_comments: int, fmt: str, output: str, debug: bool):
        """Fetch new comments from the last video of each channel in a theme."""
        state = _load_state()
        themes = state.get("lists", {})

        if theme not in themes:
            raise click.ClickException(f"Theme '{theme}' not found.")

        channels = themes[theme].get("channels", {})
        if not channels:
            raise click.ClickException(f"No channels in theme '{theme}'.")

        config = load_config()
        client = build_youtube_client(config)

        all_comments = []

        for ch_id, ch_info in channels.items():
            ch_name = ch_info.get("name", ch_id)
            last_fetch = ch_info.get("last_fetch")

            if debug:
                click.echo(f"\n[DEBUG] Processing channel: {ch_name} ({ch_id})", err=True)
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
                        comment_time = datetime.fromisoformat(comment.published_at.replace("Z", "+00:00"))
                        fetch_time = datetime.fromisoformat(last_fetch.replace("Z", "+00:00"))
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
                comment_dict["source_channel_name"] = ch_name
                new_comments.append(comment_dict)

            if debug:
                click.echo(f"[DEBUG] Found {len(new_comments)} new comments from {ch_name}", err=True)

            all_comments.extend(new_comments)

            # Update last_fetch timestamp for this channel
            # Use the earliest comment time or current time
            if new_comments:
                # Update to now so next fetch only gets newer ones
                channels[ch_id]["last_fetch"] = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

        # Update last_fetch for channels with no comments too (they were checked)
        for ch_id, ch_info in channels.items():
            if ch_info.get("last_fetch") is None or ch_id in [
                c["source_channel_id"] for c in all_comments
            ]:
                channels[ch_id]["last_fetch"] = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

        _save_state(state)

        # Output
        if output:
            Path(output).write_text(
                json.dumps(all_comments, ensure_ascii=False, default=str)
                if fmt == "json"
                else dump_yaml(all_comments)
            )
            click.echo(f"Saved {len(all_comments)} comments to {output}")
        else:
            out(all_comments, fmt)

    return CommandManifest(
        name="hot",
        click_command=hot_group,
    )
