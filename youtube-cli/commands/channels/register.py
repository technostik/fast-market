from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click

from commands.base import CommandManifest
from commands.common.channel_search import search_channels, format_channel_entry
from common.core.config import load_youtube_config
from common.core.paths import get_youtube_channel_list_path
from common.youtube.channel_list import (
    load_channel_list_file,
    save_channel_list_file,
    ChannelListFile,
    create_channel_entry,
    slugify,
)
from core.config import load_config
from core.engine import build_youtube_client


def _get_channel_list_path() -> str:
    """Get the channel list file path from config or default."""
    yt_cfg = load_youtube_config()
    return yt_cfg.get("channel_list_path", str(get_youtube_channel_list_path()))


def _load_channel_list() -> ChannelListFile:
    """Load the channel list file."""
    path = Path(_get_channel_list_path())
    return load_channel_list_file(path)


def _save_channel_list(channel_list: ChannelListFile) -> None:
    """Save the channel list file."""
    path = Path(_get_channel_list_path())
    save_channel_list_file(path, channel_list)


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("channels", invoke_without_command=True)
    @click.pass_context
    def channels_group(ctx):
        """Manage the channel list file.

        Subcommands:
          add    Add a channel to the list
          list   List all channels
          remove Remove a channel from the list
        """
        if ctx.invoked_subcommand is None:
            click.echo("Usage: youtube channels <command>")
            click.echo("")
            click.echo("Commands:")
            click.echo("  add    Add a channel to the list")
            click.echo("  list   List all channels")
            click.echo("  remove Remove a channel from the list")
            click.echo("  edit   Edit the channel list file in editor")
            click.echo("")
            click.echo("Examples:")
            click.echo("  youtube channels add                    # Interactive wizard")
            click.echo("  youtube channels list                   # List all channels")
            click.echo("  youtube channels list -f json           # JSON output")
            click.echo("  youtube channels remove UC...           # Remove by channel ID")
            click.echo("  youtube channels edit                   # Edit channel list file")

    # ─── ADD ────────────────────────────────────────────────────────────

    @channels_group.command("add")
    @click.argument("search_query", required=False)
    @click.option("--channel-id", "-c", default=None, help="Channel ID (skips search wizard)")
    @click.option("--name", default=None, help="Channel display name (auto-fetched if not given)")
    def add_cmd(search_query: str, channel_id: str, name: str):
        """Add a channel to the list.

        SEARCH_QUERY: Optional search string to pre-populate the wizard.
        """
        channel_list = _load_channel_list()

        # Determine channel
        if not channel_id:
            if not search_query:
                search_query = input("Search for a channel (name/keyword): ").strip()
            if not search_query:
                raise click.ClickException("No search query provided.")

            max_results = 10
            click.echo(f"\nSearching for channels matching '{search_query}'...")

            results = search_channels(search_query, max_results)
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
            # Fetch full details if not provided
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

        # Check if channel already exists
        channel_name = slugify(title)
        if channel_list.get_channel_by_name(channel_name):
            raise click.ClickException(f"Channel '{title}' already exists in the list.")

        # Create channel entry
        channel_entry = create_channel_entry(
            channel_id=channel_id,
            title=title,
            name=channel_name,
            subscribers=subscribers,
            description=description,
        )

        # Add to global channels list
        channel_list.channels.append(channel_entry)
        _save_channel_list(channel_list)

        click.echo(f"\nAdded '{title}' ({channel_id}) to channel list.")
        click.echo(f"  Name (slugified): {channel_name}")
        click.echo(f"  Subscribers: {subscribers:,}")

    # ─── LIST ───────────────────────────────────────────────────────────

    @channels_group.command("list")
    @click.option("--format", "-f", "fmt", type=click.Choice(["json", "yaml", "text"]), default="text")
    def list_cmd(fmt: str):
        """List all channels."""
        channel_list = _load_channel_list()
        channels = channel_list.channels

        if not channels:
            click.echo("No channels in the list. Use 'youtube channels add' to add one.")
            return

        if fmt == "text":
            click.echo(f"# Channel list file: {_get_channel_list_path()}")
            click.echo(f"# Total channels: {len(channels)}")
            click.echo("")

            for ch in channels:
                subs = f" ({ch.subscribers:,} subscribers)" if ch.subscribers > 0 else ""
                click.echo(f"  {ch.title}{subs}")
                click.echo(f"    Name (slugified): {ch.name}")
                click.echo(f"    ID: {ch.id}")
                click.echo(f"    Added: {ch.date_added}")
                
                if ch.description:
                    desc = ch.description[:100] + "..." if len(ch.description) > 100 else ch.description
                    click.echo(f"    Description: {desc}")
                
                # Show which thematics this channel belongs to
                thematics = [
                    t.name for t in channel_list.thematics
                    if ch.name in t.channels
                ]
                if thematics:
                    click.echo(f"    Thematics: {', '.join(thematics)}")
                click.echo("")
        else:
            from common.cli.helpers import out
            results = [ch.to_dict() for ch in channels]
            out(results, fmt)

    # ─── REMOVE ─────────────────────────────────────────────────────────

    @channels_group.command("remove")
    @click.argument("channel_id")
    @click.option("--force", "-f", is_flag=True, help="Remove from thematics as well")
    def remove_cmd(channel_id: str, force: bool):
        """Remove a channel from the list."""
        channel_list = _load_channel_list()

        # Find channel by ID
        channel_entry = None
        for ch in channel_list.channels:
            if ch.id == channel_id:
                channel_entry = ch
                break

        if not channel_entry:
            raise click.ClickException(f"Channel '{channel_id}' not found.")

        # Check if channel is in any thematic
        thematics_with_channel = [
            t.name for t in channel_list.thematics
            if channel_entry.name in t.channels
        ]

        if thematics_with_channel and not force:
            raise click.ClickException(
                f"Channel '{channel_entry.name}' is in thematics: {', '.join(thematics_with_channel)}. "
                f"Use --force to remove from thematics as well."
            )

        # Remove from thematics
        for thematic in channel_list.thematics:
            thematic.remove_channel(channel_entry.name)

        # Remove from global list
        channel_list.channels = [
            ch for ch in channel_list.channels if ch.id != channel_id
        ]

        _save_channel_list(channel_list)
        click.echo(f"Removed '{channel_entry.name}' ({channel_id}) from channel list.")

    # ─── EDIT ─────────────────────────────────────────────────────────

    @channels_group.command("edit")
    @click.option("--editor", help="Editor to use (default: $EDITOR or nano)")
    def edit_cmd(editor: str):
        """Edit the channel list file in your preferred editor."""
        from common.core.config import load_common_config

        channel_list_path = Path(_get_channel_list_path())

        # Determine editor
        if not editor:
            common_cfg = load_common_config()
            editor = common_cfg.get("default_editor") or os.environ.get("EDITOR", "nano")

        # Ensure file exists
        if not channel_list_path.exists():
            # Create empty file with structure
            from common.youtube.channel_list import ChannelListFile, save_channel_list_file
            save_channel_list_file(channel_list_path, ChannelListFile())

        click.echo(f"Opening channel list file in {editor}...")
        click.echo(f"  File: {channel_list_path}")
        click.echo("")
        
        subprocess.run([editor, str(channel_list_path)])

        # Validate after editing
        try:
            channel_list = _load_channel_list()
            click.echo(f"")
            click.echo(f"Channel list file saved successfully.")
            click.echo(f"  Channels: {len(channel_list.channels)}")
            click.echo(f"  Thematics: {', '.join(channel_list.list_thematic_names()) or 'none'}")
        except Exception as e:
            click.echo(f"")
            click.echo(f"Warning: Failed to validate edited file: {e}", err=True)

    return CommandManifest(
        name="channels",
        click_command=channels_group,
    )
