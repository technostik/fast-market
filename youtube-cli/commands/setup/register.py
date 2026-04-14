from __future__ import annotations

import shutil
from pathlib import Path

import click

from commands.base import CommandManifest
from common.core.paths import get_tool_config, get_youtube_config_path, get_youtube_channel_list_path
from common.core.config import load_youtube_config, save_youtube_config
from common.youtube.auth import YouTubeOAuth, SCOPE_FULL
from common.youtube.channel_list import (
    load_channel_list_file,
    save_channel_list_file,
    ChannelListFile,
)


def _ask(prompt: str, default: str = "") -> str:
    if default:
        prompt = f"{prompt} [{default}]"
    value = input(f"{prompt}: ").strip()
    return value if value else default


def register(plugin_manifests: dict) -> CommandManifest:
    @click.group("setup", invoke_without_command=True)
    @click.pass_context
    def setup_group(ctx):
        """Setup and manage YouTube configuration."""
        if ctx.invoked_subcommand is None:
            click.echo("Usage: youtube setup <command>")
            click.echo("")
            click.echo("Commands:")
            click.echo("  show           Display current configuration")
            click.echo("  locate         Show config file locations")
            click.echo("  wizard         Interactive setup wizard")
            click.echo("  reset          Reset config to defaults (backs up existing)")
            click.echo("  refresh-auth   Re-authenticate with full API access")
            click.echo("  channel-list   Manage channel list file")
            click.echo("")
            click.echo("First time setup:")
            click.echo("  1. youtube setup wizard")
            click.echo("  2. Ensure client_secret.json exists at the configured path")
            click.echo("  3. Run 'youtube search test' to authenticate")

    @setup_group.command("show")
    def show_cmd():
        """Display current configuration."""
        yt_cfg_path = get_youtube_config_path()
        if yt_cfg_path.exists():
            click.echo(f"# Shared youtube configuration ({yt_cfg_path}):")
            click.echo(yt_cfg_path.read_text())
        else:
            click.echo("No shared youtube configuration found. Use 'setup wizard' to create.")

        cfg_path = get_tool_config("youtube")
        if cfg_path.exists():
            click.echo(f"\n# Tool config (legacy) ({cfg_path}):")
            click.echo(cfg_path.read_text())

    @setup_group.command("locate")
    def locate_cmd():
        """Show config file locations."""
        cfg_path = get_tool_config("youtube")

        click.echo(f"Shared youtube config: {get_youtube_config_path()}")
        if get_youtube_config_path().exists():
            click.echo("  Status: exists")
        else:
            click.echo("  Status: does not exist (use 'setup wizard' to create)")

        channel_list_path = get_youtube_channel_list_path()
        click.echo(f"Channel list file: {channel_list_path}")
        if channel_list_path.exists():
            click.echo("  Status: exists")
        else:
            click.echo("  Status: does not exist (use 'youtube hot add' to create)")

        click.echo(f"Tool config (legacy): {cfg_path}")
        if cfg_path.exists():
            click.echo("  Status: exists")
        else:
            click.echo("  Status: does not exist")

        secret_path = get_youtube_config_path().parent / "client_secret.json"
        click.echo(f"Client secret: {secret_path}")
        if secret_path.exists():
            click.echo("  Status: exists")
        else:
            click.echo("  Status: does not exist")

        token_path = get_youtube_config_path().parent / "token.json"
        click.echo(f"OAuth token: {token_path}")
        if token_path.exists():
            click.echo("  Status: exists (authenticated)")
        else:
            click.echo("  Status: does not exist (run a command to authenticate)")

    @setup_group.command("wizard")
    def wizard_cmd():
        """Interactive setup wizard."""
        yt_cfg_path = get_youtube_config_path()
        existing = load_youtube_config()

        click.echo("=== YouTube Setup Wizard ===")
        click.echo("Press Enter to keep current value. Type a new value to change it.")
        click.echo("")

        # channel_id
        current_channel = existing.get("channel_id", "")
        click.echo("youtube.channel_id (shared across all tools)")
        click.echo(f"  current: {current_channel or '(not set)'}")
        channel_id = _ask("  channel_id", default=current_channel)
        if channel_id and channel_id != current_channel:
            click.echo(f"  → {channel_id}")
        elif not channel_id:
            click.echo("  → unchanged (empty)")
        else:
            click.echo("  → unchanged")

        click.echo("")

        # client_secret_path
        current_secret = existing.get("client_secret_path", str(get_youtube_config_path().parent / "client_secret.json"))
        click.echo("youtube.client_secret_path")
        click.echo(f"  current: {current_secret or '(not set)'}")
        client_secret = _ask("  client_secret_path", default=current_secret)
        if client_secret:
            secret_p = Path(client_secret).expanduser()
            if not secret_p.exists():
                click.echo(f"  Warning: file not found: {secret_p}")
            if client_secret != current_secret:
                click.echo(f"  → {client_secret}")
            else:
                click.echo("  → unchanged")
        else:
            click.echo("  → unchanged")

        click.echo("")

        # quota_limit
        current_quota = existing.get("quota_limit", 10000)
        click.echo("youtube.quota_limit")
        click.echo(f"  current: {current_quota}")
        raw = _ask("  quota_limit", default=str(current_quota))
        try:
            quota_limit = int(raw)
            if quota_limit != current_quota:
                click.echo(f"  → {quota_limit}")
            else:
                click.echo("  → unchanged")
        except ValueError:
            quota_limit = current_quota
            click.echo("  invalid integer, keeping current value")

        click.echo("")

        # channel_list_path
        current_channel_list = existing.get(
            "channel_list_path", str(get_youtube_channel_list_path())
        )
        click.echo("youtube.channel_list_path (shared channel list file)")
        click.echo(f"  current: {current_channel_list or '(not set)'}")
        channel_list_path = _ask("  channel_list_path", default=current_channel_list)
        if channel_list_path and channel_list_path != current_channel_list:
            click.echo(f"  → {channel_list_path}")
        elif not channel_list_path:
            click.echo("  → unchanged (using default)")
        else:
            click.echo("  → unchanged")

        click.echo("")

        # default_thematic
        current_default_thematic = existing.get("default_thematic", "")
        click.echo("youtube.default_thematic (default thematic for hot commands)")
        click.echo(f"  current: {current_default_thematic or '(not set)'}")
        default_thematic = _ask("  default_thematic", default=current_default_thematic)
        if default_thematic and default_thematic != current_default_thematic:
            click.echo(f"  → {default_thematic}")
        elif not default_thematic:
            click.echo("  → unchanged (not set)")
        else:
            click.echo("  → unchanged")

        click.echo("")

        # Save
        new_yt_cfg = {}
        if channel_id:
            new_yt_cfg["channel_id"] = channel_id
        if client_secret:
            new_yt_cfg["client_secret_path"] = client_secret
        new_yt_cfg["quota_limit"] = quota_limit
        if channel_list_path:
            new_yt_cfg["channel_list_path"] = channel_list_path
        if default_thematic:
            new_yt_cfg["default_thematic"] = default_thematic

        save_youtube_config(new_yt_cfg)
        click.echo(f"Saved shared youtube config to {yt_cfg_path}")
        click.echo("")
        click.echo("Next steps:")
        click.echo("  1. Ensure client_secret.json exists at the configured path")
        click.echo("  2. Run 'youtube search test' to authenticate")

    @setup_group.command("reset")
    def reset_cmd():
        """Reset config to defaults (backs up existing)."""
        yt_cfg_path = get_youtube_config_path()
        if yt_cfg_path.exists():
            backup_path = yt_cfg_path.with_name("config.yaml.bak")
            shutil.copy2(str(yt_cfg_path), str(backup_path))
            click.echo(f"Backed up existing shared config to {backup_path}")
        yt_cfg_path.parent.mkdir(parents=True, exist_ok=True)
        yt_cfg_path.write_text("# YouTube shared configuration\nchannel_id: \"\"\nquota_limit: 10000\n# client_secret_path: ~/.config/fast-market/common/youtube/client_secret.json\n")
        click.echo(f"Reset shared configuration to defaults at {yt_cfg_path}")

    @setup_group.command("refresh-auth")
    def refresh_auth_cmd(**kwargs):
        """Re-authenticate with full API access (youtube.force-ssl scope).

        Use this when you get 'insufficientPermissions' errors.
        This deletes the existing token, forces Google to re-show the
        consent screen with full permissions, and re-authenticates.
        """
        yt_cfg = load_youtube_config()
        client_secret = yt_cfg.get("client_secret_path")

        if client_secret:
            client_secret = str(Path(client_secret).expanduser())
        else:
            from common.youtube.auth import get_client_secret_path
            client_secret = get_client_secret_path()

        secret_path = Path(client_secret)
        if not secret_path.exists():
            click.echo(f"Error: client_secret.json not found at {secret_path}")
            click.echo("Run 'youtube setup wizard' to configure it first.")
            raise SystemExit(1)

        click.echo("=== YouTube Auth Refresh ===")
        click.echo(f"Client secret: {secret_path}")
        click.echo("")
        click.echo("This will delete your existing token and re-authenticate.")
        click.echo("The browser will open. You MUST grant ALL requested permissions.")
        click.echo("")

        auth = YouTubeOAuth(client_secret)
        auth.refresh_auth(scopes=[SCOPE_FULL])

        click.echo("")
        click.echo("Authentication refreshed successfully.")
        click.echo("You now have full API access (youtube.force-ssl scope).")

    @setup_group.group("channel-list", invoke_without_command=True)
    @click.pass_context
    def channel_list_group(ctx):
        """Manage the channel list file.

        Subcommands:
          show           Display channel list file
          locate         Show channel list file path
          set-default    Set the default thematic for hot commands
        """
        if ctx.invoked_subcommand is None:
            click.echo("Usage: youtube setup channel-list <command>")
            click.echo("")
            click.echo("Commands:")
            click.echo("  show           Display channel list file")
            click.echo("  locate         Show channel list file path")
            click.echo("  set-default    Set default thematic for hot commands")
            click.echo("")

    @channel_list_group.command("show")
    @click.option("--format", "-f", "fmt", type=click.Choice(["json", "yaml", "text"]), default="text")
    def channel_list_show_cmd(fmt: str):
        """Display current channel list file."""
        from common.cli.helpers import out
        from common.core.yaml_utils import dump_yaml
        import json

        yt_cfg = load_youtube_config()
        channel_list_path = Path(
            yt_cfg.get("channel_list_path", str(get_youtube_channel_list_path()))
        ).expanduser()

        if not channel_list_path.exists():
            click.echo(f"No channel list file at {channel_list_path}")
            click.echo("Use 'youtube hot add' to create one.")
            return

        channel_list = load_channel_list_file(channel_list_path)

        if fmt == "text":
            click.echo(f"# Channel list file: {channel_list_path}")
            click.echo(f"# Total channels: {len(channel_list.channels)}")
            click.echo(f"# Thematics: {', '.join(channel_list.list_thematic_names()) or 'none'}")
            click.echo("")
            
            # Show thematics
            for thematic in channel_list.thematics:
                click.echo(f"=== {thematic.name} ({len(thematic.channels)} channels) ===")
                for ch_name in thematic.channels:
                    # Resolve channel from global list
                    ch_entry = channel_list.get_channel_by_name(ch_name)
                    if ch_entry:
                        subs = f" ({ch_entry.subscribers:,} subscribers)" if ch_entry.subscribers > 0 else ""
                        click.echo(f"  {ch_entry.title}{subs}")
                        click.echo(f"    Name: {ch_entry.name}")
                        click.echo(f"    ID: {ch_entry.id}")
                    else:
                        click.echo(f"  {ch_name} (not found in channel list)")
                click.echo("")
        else:
            data = channel_list.to_dict()
            if fmt == "json":
                click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
            else:
                click.echo(dump_yaml(data))

    @channel_list_group.command("locate")
    def channel_list_locate_cmd():
        """Show channel list file path."""
        yt_cfg = load_youtube_config()
        channel_list_path = Path(
            yt_cfg.get("channel_list_path", str(get_youtube_channel_list_path()))
        ).expanduser()

        click.echo(f"Channel list file: {channel_list_path}")
        if channel_list_path.exists():
            click.echo("  Status: exists")
        else:
            click.echo("  Status: does not exist")

    @channel_list_group.command("set-default")
    @click.argument("thematic")
    def channel_list_set_default_cmd(thematic: str):
        """Set the default thematic for hot commands."""
        from common.core.config import save_youtube_channel_list_config
        
        save_youtube_channel_list_config(default_thematic=thematic)
        click.echo(f"Default thematic set to: {thematic}")
        click.echo("")
        click.echo("Now you can run:")
        click.echo("  youtube hot fetch-comment   # without specifying a theme")
        click.echo("  youtube hot fetch-video     # without specifying a theme")

    return CommandManifest(
        name="setup",
        click_command=setup_group,
    )
